"""语义文件搜索 · 托盘程序入口。

单文件 exe 运行：系统托盘 + 内置 Win+Alt+S 全局热键 + 搜索窗。
不依赖 AutoHotkey；模型与服务放在 exe 同目录的 bin/ 下。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import ttk

# ---------- 路径解析（兼容源码运行与 PyInstaller onefile）----------
def _find_bin_dir(exe_dir):
    """资源目录：优先 exe 同目录的 bin/，其次 exe 上级的 bin/。"""
    same = os.path.join(exe_dir, "bin")
    if os.path.exists(os.path.join(same, "embeddinggemma-300M-Q8_0.gguf")):
        return same
    parent = os.path.join(os.path.dirname(exe_dir), "bin")
    if os.path.exists(os.path.join(parent, "embeddinggemma-300M-Q8_0.gguf")):
        return parent
    return same


if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    BIN_DIR = _find_bin_dir(APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR
    BIN_DIR = os.path.join(os.path.dirname(APP_DIR), "bin")

sys.path.insert(0, BUNDLE_DIR)
import search_core  # noqa: E402

MODEL_PATH = os.path.join(BIN_DIR, "embeddinggemma-300M-Q8_0.gguf")
SERVER_PATH = os.path.join(BIN_DIR, "llama-server.exe")
EVERYTHING_EXE = r"C:\Program Files (x86)\Everything\Everything.exe"

# ---------- Windows 常量 ----------
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
VK_S = 0x53
HOTKEY_ID = 1
HOTKEY_ID_QUIT = 2

DEBOUNCE_MS = 260
MAX_ROWS = 14
APP_TITLE = "语义搜索"


# ---------- 服务管理 ----------
def _port_open(port: int, timeout: float = 0.4) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _process_running(name: str) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/fi", f"imagename eq {name}", "/fo", "csv"],
            capture_output=True, timeout=5,
        ).stdout.decode("gbk", "replace")
        return name.lower() in out.lower() and "info" not in out.lower()
    except Exception:
        return False


def ensure_services():
    """后台拉起依赖服务，不阻塞界面。"""
    def worker():
        # 1. Everything 桌面客户端
        try:
            if not ctypes.windll.user32.FindWindowW(None, "Everything"):
                if os.path.exists(EVERYTHING_EXE):
                    subprocess.Popen(
                        [EVERYTHING_EXE],
                        creationflags=0x00000008,
                        close_fds=True,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
        except Exception:
            pass

        # 2a. 依赖缺失时后台自动下载（模型 + llama.cpp + SDK）
        if not os.path.exists(MODEL_PATH) or not os.path.exists(SERVER_PATH):
            try:
                import setup_deps
                setup_deps.main()
            except Exception:
                pass

        # 2b. 嵌入服务（llama.cpp）
        if os.path.exists(MODEL_PATH) and os.path.exists(SERVER_PATH) and not _port_open(8080):
            try:
                subprocess.Popen(
                    [
                        SERVER_PATH, "-m", MODEL_PATH, "-c", "1024",
                        "--embeddings", "--port", "8080",
                        "--host", "127.0.0.1", "-ngl", "0",
                    ],
                    creationflags=0x00000008,
                    close_fds=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=BIN_DIR,
                )
            except Exception:
                pass

        # 3. 让 search_core 用 exe 同目录的 SDK dll
        sdk_dll = os.path.join(BIN_DIR, "Everything64.dll")
        if os.path.exists(sdk_dll):
            search_core.sdk.DLL_PATH = sdk_dll
            search_core.sdk._dll = None

    threading.Thread(target=worker, daemon=True).start()


# ---------- 搜索窗 ----------
class SearchWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("860x480")
        self.root.resizable(False, False)
        self.root.withdraw()

        self.hits = []
        self.timer = None
        self.seq = 0

        self._build_ui()
        self._center()
        self._bind_keys()

    def _build_ui(self):
        frame = tk.Frame(self.root, padx=12, pady=10)
        frame.pack(fill="both", expand=True)

        top = tk.Frame(frame)
        top.pack(fill="x", pady=(0, 8))
        self.entry = tk.Entry(top, font=("Microsoft YaHei UI", 15))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.status = tk.Label(top, text="", font=("Microsoft YaHei UI", 9), fg="#666")
        self.status.pack(side="right", padx=(10, 0))

        cols = ("name", "score", "path")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=MAX_ROWS)
        self.tree.heading("name", text="文件名")
        self.tree.heading("score", text="相关度")
        self.tree.heading("path", text="路径")
        self.tree.column("name", width=240, anchor="w")
        self.tree.column("score", width=70, anchor="center")
        self.tree.column("path", width=520, anchor="w")
        self.tree.pack(fill="both", expand=True)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=vsb.set)

        bottom = tk.Label(
            frame,
            text="↑↓ 选择   Enter 打开   Ctrl+C 复制路径   Esc 隐藏   托盘右键退出   Win+S 保持系统搜索",
            font=("Microsoft YaHei UI", 9),
            fg="#888",
        )
        bottom.pack(fill="x", pady=(8, 0))

    def _center(self):
        self.root.update_idletasks()
        w, h = 860, 480
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _bind_keys(self):
        self.entry.bind("<KeyRelease>", self._on_type)
        self.root.bind("<Escape>", lambda e: self.hide())
        self.root.bind("<Down>", self._move(+1))
        self.root.bind("<Up>", self._move(-1))
        self.root.bind("<Return>", self._open_selected)
        self.root.bind("<Control-c>", self._copy_path)
        self.tree.bind("<Double-Button-1>", self._open_selected)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

    def show(self):
        self.root.after(0, self._show_impl)

    def _show_impl(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.attributes("-topmost", False)
        self.root.attributes("-topmost", True)
        self.entry.delete(0, "end")
        self.entry.focus_force()
        self._clear_results()
        self.status.config(text="")

    def hide(self):
        self.root.after(0, self.root.iconify)

    def _clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _on_type(self, event=None):
        if self.timer:
            self.root.after_cancel(self.timer)
        self.timer = self.root.after(DEBOUNCE_MS, self._run_search)

    def _run_search(self):
        q = self.entry.get().strip()
        if not q:
            self._clear_results()
            self.status.config(text="")
            return
        self.seq += 1
        seq = self.seq
        self.status.config(text="搜索中…")

        def worker():
            try:
                rows = search_core.search(q, limit=MAX_ROWS)
            except Exception:
                rows = []
            self.root.after(0, lambda: self._render(seq, rows))

        threading.Thread(target=worker, daemon=True).start()

    def _render(self, seq, rows):
        if seq != self.seq:
            return
        self.hits = rows
        self._clear_results()
        for h in rows:
            self.tree.insert("", "end", values=(h.name, f"{h.combined:.2f}", h.path))
        if rows:
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
        self.status.config(text=f"{len(rows)} 条")

    def _selected_hit(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = self.tree.index(sel[0])
        return self.hits[idx] if idx < len(self.hits) else None

    def _move(self, delta):
        def handler(event):
            items = self.tree.get_children()
            if not items:
                return "break"
            sel = self.tree.selection()
            cur = self.tree.index(sel[0]) if sel else 0
            nxt = max(0, min(len(items) - 1, cur + delta))
            self.tree.selection_set(items[nxt])
            self.tree.focus(items[nxt])
            self.tree.see(items[nxt])
            return "break"
        return handler

    def _open_selected(self, event=None):
        hit = self._selected_hit()
        if hit and os.path.exists(hit.path):
            try:
                os.startfile(hit.path)
            except OSError:
                pass
            self.hide()
        return "break"

    def _copy_path(self, event=None):
        hit = self._selected_hit()
        if hit:
            self.root.clipboard_clear()
            self.root.clipboard_append(hit.path)
            self.status.config(text="已复制路径")
        return "break"

    def run(self):
        self.root.mainloop()

    def quit(self):
        """线程安全地退出主循环。"""
        def do_quit():
            try:
                self.root.quit()
            except Exception:
                pass
        try:
            self.root.after(0, do_quit)
        except Exception:
            pass


# ---------- 全局热键（Windows 原生，无 AHK 依赖）----------
class HotkeyManager:
    """在独立线程注册全局热键并跑消息循环。"""

    def __init__(self, on_search, on_quit):
        self.on_search = on_search
        self.on_quit = on_quit
        self.user32 = ctypes.windll.user32
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        user32 = self.user32
        ok1 = user32.RegisterHotKey(None, HOTKEY_ID, MOD_WIN | MOD_ALT, VK_S)
        # Win+Alt+Q 退出（备用）
        ok2 = user32.RegisterHotKey(None, HOTKEY_ID_QUIT, MOD_WIN | MOD_ALT, 0x51)
        if not ok1:
            # 热键被占用时静默降级，托盘仍可用
            pass

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_ID:
                    self.on_search()
                elif msg.wParam == HOTKEY_ID_QUIT:
                    self.on_quit()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if ok1:
            user32.UnregisterHotKey(None, HOTKEY_ID)
        if ok2:
            user32.UnregisterHotKey(None, HOTKEY_ID_QUIT)


# ---------- 开机自启（写 HKCU Run）----------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "SemanticSearch"


def is_autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return bool(value)
    except Exception:
        return False


def set_autostart(enabled):
    try:
        import winreg
        if enabled:
            exe = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
            cmd = f'"{exe}"'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, cmd)
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
                try:
                    winreg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


# ---------- 系统托盘 ----------
def make_icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 放大镜图标：蓝色圆环 + 手柄
    d.ellipse((8, 8, 42, 42), outline=(30, 120, 220, 255), width=6)
    d.line((38, 38, 56, 56), fill=(30, 120, 220, 255), width=8)
    return img


def run_tray(on_open, on_quit):
    import pystray

    def autostart_item(icon, item):
        ok = set_autostart(not item.checked)
        if ok:
            item.checked = not item.checked

    autostart = pystray.MenuItem(
        "开机自启",
        autostart_item,
        checked=lambda item: is_autostart_enabled(),
    )
    menu = pystray.Menu(
        pystray.MenuItem("打开搜索", on_open, default=True),
        autostart,
        pystray.MenuItem("退出", on_quit),
    )
    icon = pystray.Icon(APP_TITLE, make_icon_image(), "语义搜索（Win+Alt+S）", menu)
    icon.run()


# ---------- 主流程 ----------
def main():
    ensure_services()

    window = SearchWindow()
    hotkeys = HotkeyManager(on_search=window.show, on_quit=window.quit)

    def quit_all(icon=None, item=None):
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        window.quit()
        # 兜底：1.5 秒后强制退出，避免托盘/热键线程残留
        def force_exit():
            time.sleep(1.5)
            os._exit(0)
        threading.Thread(target=force_exit, daemon=True).start()

    hotkeys.start()

    tray_thread = threading.Thread(
        target=run_tray, args=(window.show, quit_all), daemon=True
    )
    tray_thread.start()

    window.run()


if __name__ == "__main__":
    main()
