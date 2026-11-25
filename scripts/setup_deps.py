"""一键下载运行所需依赖（模型 + llama.cpp + Everything SDK）。

用法：python scripts/setup_deps.py
下载到项目根目录的 bin/ 下。全部使用国内高速源。
"""
from __future__ import annotations

import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
os.makedirs(BIN, exist_ok=True)

MODEL = "embeddinggemma-300M-Q8_0.gguf"
MODEL_URL = (
    "https://www.modelscope.cn/models/ggml-org/"
    "embeddinggemma-300M-GGUF/resolve/master/embeddinggemma-300M-Q8_0.gguf"
)
# llama.cpp CPU 运行所需文件（GitHub release，体积小的核心 DLL）
LLAMA_BASE = "https://github.com/ggml-org/llama.cpp/releases/download/b9993/"
LLAMA_FILES = [
    "llama-server.exe",
    "llama-server-impl.dll",
    "llama-common.dll",
    "llama.dll",
    "ggml.dll",
    "ggml-base.dll",
    "ggml-cpu-x64.dll",
    "libomp140.x86_64.dll",
]
SDK_URL = "https://www.voidtools.com/Everything-SDK.zip"


def download(url, path, label):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"[skip] {label} 已存在")
        return True
    tmp = path + ".download"
    print(f"[下载] {label} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
            total = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                if total % (10 * 1024 * 1024) < 262144:
                    print(f"  {total / 1024 / 1024:.0f} MB", flush=True)
        os.replace(tmp, path)
        print(f"[完成] {label} ({os.path.getsize(path) / 1024 / 1024:.1f} MB)")
        return True
    except Exception as e:
        print(f"[失败] {label}: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def main():
    print("=" * 50)
    print("语义搜索 · 依赖安装")
    print("=" * 50)
    ok = True

    ok &= download(MODEL_URL, os.path.join(BIN, MODEL), "EmbeddingGemma 模型")
    for name in LLAMA_FILES:
        ok &= download(LLAMA_BASE + name, os.path.join(BIN, name), name)

    # Everything SDK：只需要 Everything64.dll
    sdk_zip = os.path.join(BIN, "Everything-SDK.zip")
    dll = os.path.join(BIN, "Everything64.dll")
    if not os.path.exists(dll):
        if download(SDK_URL, sdk_zip, "Everything SDK"):
            import zipfile
            try:
                with zipfile.ZipFile(sdk_zip) as z:
                    for n in z.namelist():
                        if n.endswith("Everything64.dll"):
                            with z.open(n) as src, open(dll, "wb") as dst:
                                dst.write(src.read())
                            print("[完成] Everything64.dll")
                            break
            except Exception as e:
                print(f"[失败] 解压 SDK: {e}")
                ok = False

    print("=" * 50)
    if ok:
        print("全部就绪。运行 dist\\SemanticSearch.exe 或源码 python scripts/app.py")
    else:
        print("部分下载失败，可重新运行本脚本续传。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
