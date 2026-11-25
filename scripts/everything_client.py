"""Everything SDK 的 Python ctypes 封装（64 位）。"""
import ctypes
import os

DLL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bin", "SDK", "dll", "Everything64.dll",
)

EVERYTHING_REQUEST_FILE_NAME = 0x00000001
EVERYTHING_REQUEST_PATH = 0x00000002
EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004
EVERYTHING_REQUEST_EXTENSION = 0x00000008
EVERYTHING_REQUEST_SIZE = 0x00000010
EVERYTHING_REQUEST_DATE_MODIFIED = 0x00000040

_REQUEST_FLAGS = (
    EVERYTHING_REQUEST_FILE_NAME
    | EVERYTHING_REQUEST_PATH
    | EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME
    | EVERYTHING_REQUEST_EXTENSION
    | EVERYTHING_REQUEST_SIZE
    | EVERYTHING_REQUEST_DATE_MODIFIED
)

_dll = None


def _get_dll():
    global _dll
    if _dll is None:
        _dll = ctypes.WinDLL(DLL_PATH)
        _dll.Everything_GetResultFullPathNameW.argtypes = [
            ctypes.c_int, ctypes.c_wchar_p, ctypes.c_int,
        ]
        _dll.Everything_GetResultFullPathNameW.restype = ctypes.c_int
        _dll.Everything_SetSearchW.argtypes = [ctypes.c_wchar_p]
        _dll.Everything_SetRequestFlags.argtypes = [ctypes.c_uint]
        _dll.Everything_QueryW.argtypes = [ctypes.c_int]
        _dll.Everything_QueryW.restype = ctypes.c_int
        _dll.Everything_GetNumResults.restype = ctypes.c_int
        _dll.Everything_GetResultSize.argtypes = [
            ctypes.c_int, ctypes.POINTER(ctypes.c_ulonglong),
        ]
        _dll.Everything_SortResultsByPath.restype = None
    return _dll


def search(query: str, max_results: int = 300, sort_by_path: bool = False):
    """返回 [(full_path, size_bytes), ...]。Everything 必须后台运行。"""
    if not query or not query.strip():
        return []
    dll = _get_dll()
    dll.Everything_SetSearchW(query)
    dll.Everything_SetRequestFlags(_REQUEST_FLAGS)
    dll.Everything_SetMax(max_results)
    if not dll.Everything_QueryW(1):
        raise RuntimeError(f"Everything 查询失败: {query!r}")
    if sort_by_path:
        dll.Everything_SortResultsByPath()
    out = []
    buf = ctypes.create_unicode_buffer(520)
    size = ctypes.c_ulonglong(0)
    for i in range(min(dll.Everything_GetNumResults(), max_results)):
        dll.Everything_GetResultFullPathNameW(i, buf, 520)
        path = buf.value
        if not path:
            continue
        dll.Everything_GetResultSize(i, ctypes.byref(size))
        out.append((path, size.value))
    return out


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "README"
    rows = search(q, 10)
    print(f"命中 {len(rows)} 条")
    for p, s in rows[:10]:
        print(f"{s:>12}  {p}")
