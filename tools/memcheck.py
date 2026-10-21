"""Memory budget check: starts Getman, exercises it like a user would and
reports the process memory the OS charges to it.

    python tools/memcheck.py              # print numbers
    python tools/memcheck.py --budget 50  # exit 1 if over 50 MB

Metric: Windows — private working set, exactly what the "Memory" column of
Task Manager shows (non-shareable resident pages; DLL code is excluded), read
with QueryWorkingSet; commit charge is printed for reference. Linux —
anonymous private memory (the same idea: shared library code is excluded).
macOS — RSS via psutil (upper bound).
"""
import argparse
import gc
import http.server
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("GETMAN_DATA_DIR", tempfile.mkdtemp(prefix="getman-mem-"))


def _windows_private_ws() -> float:
    """Private working set: resident pages whose "Shared" bit is clear."""
    import ctypes
    from ctypes import wintypes
    psapi, kernel32 = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.QueryWorkingSet.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    handle = kernel32.GetCurrentProcess()
    count = 1 << 16
    while True:
        buf = (ctypes.c_size_t * (count + 1))()
        if psapi.QueryWorkingSet(handle, buf, ctypes.sizeof(buf)):
            break
        count = max(count * 2, buf[0] + 4096)  # ERROR_BAD_LENGTH: buf[0] holds the entry count
    entries = buf[0]
    private = sum(1 for i in range(1, entries + 1) if not (buf[i] >> 8) & 1)
    return private * 4096 / 1024 / 1024


def _windows_commit() -> float:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                "PrivateUsage")]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.PrivateUsage / 1024 / 1024


def private_mb() -> float:
    if sys.platform.startswith("linux"):
        with open("/proc/self/smaps_rollup") as f:
            for line in f:
                if line.startswith("Anonymous:"):
                    return int(line.split()[1]) / 1024
    if sys.platform == "win32":
        return _windows_private_ws()
    try:
        import psutil
    except ImportError:
        sys.exit("psutil is required on this platform: pip install psutil")
    return psutil.Process().memory_info().rss / 1024 / 1024


def extra() -> str:
    return f"  (commit charge {_windows_commit():.1f} MB)" if sys.platform == "win32" else ""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        body = json.dumps({"items": [{"id": i, "name": f"item {i}", "tags": ["a", "b"]} for i in range(300)]})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=0, help="fail when the busy figure exceeds this (MB)")
    args = parser.parse_args()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from ui.main_window import MainWindow

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    window = MainWindow()
    window.resize(1360, 860)
    window.show()
    wait(1500)
    gc.collect()
    idle = private_mb()
    print(f"idle after start:            {idle:6.1f} MB{extra()}")

    for _ in range(4):
        window.new_tab()
    for section in window.editor.SECTIONS:
        window.editor.show_section(section)
    for i in range(40):
        window.tabbar.setCurrentIndex(i % 5)
        window.editor.url.setText(f"http://127.0.0.1:{server.server_port}/items?page={i}")
        window.send_current()
        wait(120)
        window.response.tabs.setCurrentIndex(i % 4)
    wait(1000)
    gc.collect()
    busy = private_mb()
    print(f"5 tabs, 40 requests sent:    {busy:6.1f} MB{extra()}")
    window.close()
    app.quit()
    server.shutdown()
    if args.budget and busy > args.budget:
        print(f"FAIL: {busy:.1f} MB is over the {args.budget:g} MB budget")
        return 1
    if args.budget:
        print(f"OK: within the {args.budget:g} MB budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
