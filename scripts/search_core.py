"""混合搜索核心：Everything 文件名召回 + Windows 索引内容召回 + EmbeddingGemma 语义重排。"""
from __future__ import annotations

import ctypes
import json
import math
import os
import re
import socket
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import everything_client as sdk  # noqa: E402

# 嵌入后端：优先 Ollama，可用环境变量切到 llama.cpp / LM Studio（OpenAI 兼容）
BACKEND = os.environ.get("SS_EMBED_BACKEND", "openai").lower()
OLLAMA_URL = "http://127.0.0.1:11434/api/embed"
OPENAI_URL = "http://127.0.0.1:8080/v1/embeddings"
MODEL = os.environ.get("SS_EMBED_MODEL", "embeddinggemma")
# OpenAI 兼容端点忽略 model 字段，但保留以便切换到 Ollama

# 查询/文档前缀来自 EmbeddingGemma 官方任务模板
QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: "
DOC_TEXT_SEP = " | text: "

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".json", ".yaml", ".yml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".cpp", ".h", ".hpp", ".java",
    ".go", ".rs", ".rb", ".php", ".sh", ".ps1", ".bat", ".html", ".htm", ".css",
    ".xml", ".ini", ".cfg", ".toml", ".sql", ".tex", ".lua", ".swift", ".kt",
}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "$RECYCLE.BIN"}


@dataclass
class Hit:
    path: str
    name: str = ""
    size: int = 0
    semantic: float = 0.0
    keyword: float = 0.0
    combined: float = 0.0
    source: set[str] = field(default_factory=set)
    snippet: str = ""

    def to_dict(self):
        return {
            "path": self.path,
            "name": self.name or os.path.basename(self.path),
            "size": self.size,
            "score": round(self.combined, 4),
            "semantic": round(self.semantic, 4),
            "keyword": round(self.keyword, 4),
            "source": sorted(self.source),
            "snippet": self.snippet[:200],
        }


EVERYTHING_EXE = r"C:\Program Files (x86)\Everything\Everything.exe"
_sdk_ready = False


def _ensure_everything() -> bool:
    """若桌面客户端未运行则拉起，并等待 IPC 窗口出现。"""
    global _sdk_ready
    if _sdk_ready:
        return True
    if ctypes.windll.user32.FindWindowW(None, "Everything"):
        _sdk_ready = True
        return True
    try:
        import subprocess
        subprocess.Popen(
            [EVERYTHING_EXE],
            creationflags=0x00000008,  # DETACHED_PROCESS
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    for _ in range(40):
        time.sleep(0.25)
        if ctypes.windll.user32.FindWindowW(None, "Everything"):
            _sdk_ready = True
            return True
    return False


def everything_search(query: str, limit: int = 200) -> list[Hit]:
    """关键词召回：文件名 + 路径，走 Everything SDK。"""
    safe = re.sub(r'["<>|]', " ", query).strip()
    if not safe or not _ensure_everything():
        return []
    try:
        rows = sdk.search(safe, max_results=limit)
    except Exception:
        return []
    hits = []
    for path, size in rows:
        if not os.path.isabs(path):
            continue
        if any(part in SKIP_DIRS for part in path.split(os.sep)):
            continue
        hits.append(
            Hit(path=path, name=os.path.basename(path), size=size, source={"everything"})
        )
    return hits


def windows_index_search(query: str, limit: int = 150) -> list[Hit]:
    """内容召回：查 Windows Search 索引的 SystemIndex。"""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return []
    # 构造全文检索条件，中文短语用 CONTAINS
    terms = [t for t in re.split(r"\s+", query.strip()) if t and len(t) > 1]
    if not terms:
        return []
    escaped = [t.replace("'", "''") for t in terms[:6]]
    contains = " AND ".join(f'"{t}"' for t in escaped)
    sql = (
        f"SELECT TOP {limit} System.ItemPathDisplay, System.ItemName "
        f"FROM SystemIndex WHERE SCOPE='file:' AND CONTAINS(*, '{contains}')"
    )
    hits: list[Hit] = []
    pythoncom.CoInitialize()
    try:
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
        rs = conn.Execute(sql)[0]
        while not rs.EOF:
            try:
                path = str(rs.Fields.Item("System.ItemPathDisplay").Value)
                name = str(rs.Fields.Item("System.ItemName").Value)
            except Exception:
                rs.MoveNext()
                continue
            if path and os.path.isabs(path) and os.path.exists(path):
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                hits.append(
                    Hit(path=path, name=name, size=size, source={"windows"})
                )
            rs.MoveNext()
        rs.Close()
        conn.Close()
    except Exception:
        pass
    finally:
        pythoncom.CoUninitialize()
    return hits


def read_text_snippet(path: str, max_chars: int = 1200) -> str:
    """读纯文本文件前若干字符做语义文本；二进制/大文件跳过。"""
    ext = os.path.splitext(path)[1].lower()
    if ext not in TEXT_EXTS:
        return ""
    try:
        if os.path.getsize(path) > 4 * 1024 * 1024:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except OSError:
        return ""


def build_doc_text(hit: Hit) -> str:
    """标题用文件名，正文用路径 + 内容片段（控制在 600 字符内）。"""
    parts = [os.path.dirname(hit.path).replace(os.sep, " ")]
    snippet = read_text_snippet(hit.path, max_chars=400)
    if snippet:
        parts.append(snippet)
    body = re.sub(r"\s+", " ", " ".join(parts))
    return DOC_PREFIX + hit.name + DOC_TEXT_SEP + body[:600]


def embedder_available() -> bool:
    """快速探测嵌入服务端口，避免每次搜索都等超时。"""
    port = 11434 if BACKEND == "ollama" else 8080
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def embed(texts: list[str], timeout: float = 120.0) -> list[list[float]] | None:
    """批量编码。文本必须已带任务前缀。自动在 Ollama / OpenAI 兼容后端间切换。"""
    import urllib.request

    if not embedder_available():
        return None
    if BACKEND == "ollama":
        url = OLLAMA_URL
        payload = {"model": MODEL, "input": texts}
        key = "embeddings"
    else:
        url = OPENAI_URL
        payload = {"model": MODEL, "input": texts}
        key = "data"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if key == "embeddings":
            return data.get("embeddings")
        return [row["embedding"] for row in sorted(data.get("data", []), key=lambda r: r.get("index", 0))]
    except Exception:
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def merge_hits(every: list[Hit], win: list[Hit]) -> list[Hit]:
    by_path: dict[str, Hit] = {}
    for h in every:
        by_path.setdefault(h.path.lower(), h)
    for h in win:
        if h.path.lower() in by_path:
            by_path[h.path.lower()].source.add("windows")
            by_path[h.path.lower()].snippet = h.snippet
        else:
            by_path[h.path.lower()] = h
    # 关键词排序分：Everything 在前权重高
    for rank, h in enumerate(every):
        h.keyword = max(h.keyword, 1.0 - rank / max(len(every), 1))
    for rank, h in enumerate(win):
        h.keyword = max(h.keyword, 0.7 * (1.0 - rank / max(len(win), 1)))
    return list(by_path.values())


def search(query: str, limit: int = 30) -> list[Hit]:
    every = everything_search(query, limit=150)
    win = windows_index_search(query, limit=80)
    hits = merge_hits(every, win)
    if not hits:
        return []

    q_vec_list = embed([QUERY_PREFIX + query])
    if not q_vec_list:
        # 嵌入服务不可用：退化为纯关键词
        for h in hits:
            h.combined = h.keyword
        return sorted(hits, key=lambda h: h.combined, reverse=True)[:limit]

    q_vec = q_vec_list[0]
    # 只对关键词排名靠前的候选做语义重排，控制批量大小
    candidates = sorted(hits, key=lambda h: h.keyword, reverse=True)[:80]
    doc_vecs: list[list[float]] = []
    for i in range(0, len(candidates), 4):
        batch = [build_doc_text(h) for h in candidates[i:i + 4]]
        vecs = embed(batch)
        if not vecs or len(vecs) != len(batch):
            doc_vecs = []
            break
        doc_vecs.extend(vecs)

    if len(doc_vecs) == len(candidates):
        candidate_ids = {id(h) for h in candidates}
        for h, v in zip(candidates, doc_vecs):
            h.semantic = cosine(q_vec, v)
            h.combined = 0.65 * h.semantic + 0.35 * h.keyword
        for h in hits:
            if id(h) not in candidate_ids:
                h.combined = 0.35 * h.keyword
        return sorted(hits, key=lambda h: h.combined, reverse=True)[:limit]

    for h in hits:
        h.combined = h.keyword
    return sorted(hits, key=lambda h: h.combined, reverse=True)[:limit]


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "README"
    rows = search(q, 10)
    print(f"查询: {q}  命中: {len(rows)}")
    for h in rows:
        print(f"[{h.combined:.3f}] k={h.keyword:.2f} s={h.semantic:.2f} {h.path}")
