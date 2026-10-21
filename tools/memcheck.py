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


def _windows_private_pages() -> list:
    """Addresses of resident pages whose "Shared" bit is clear (private working set)."""
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
    return [buf[i] >> 12 << 12 for i in range(1, buf[0] + 1) if not (buf[i] >> 8) & 1]


def _windows_private_ws() -> float:
    return len(_windows_private_pages()) * 4096 / 1024 / 1024


def windows_breakdown(top: int = 12) -> str:
    """Who owns the private working set: each DLL's writable/relocated pages
    vs. heaps and other private allocations."""
    import collections
    import ctypes
    from ctypes import wintypes

    class MBI(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                    ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD), ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
    kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, wintypes.DWORD]
    totals = collections.Counter()
    names = {}
    region_end, label = 0, "?"
    for va in sorted(_windows_private_pages()):
        if va >= region_end:
            mbi = MBI()
            kernel32.VirtualQuery(va, ctypes.byref(mbi), ctypes.sizeof(mbi))
            region_end = (mbi.BaseAddress or 0) + mbi.RegionSize
            if mbi.Type == 0x1000000:  # MEM_IMAGE
                base = mbi.AllocationBase or 0
                if base not in names:
                    path = ctypes.create_unicode_buffer(520)
                    kernel32.GetModuleFileNameW(base, path, 520)
                    names[base] = "image " + os.path.basename(path.value or hex(base))
                label = names[base]
            else:
                label = {0x40000: "mapped files", 0x20000: "heaps / private allocations"}.get(mbi.Type, "other")
        totals[label] += 4096
    return "\n".join(f"    {size / 1048576:6.1f} MB  {name}" for name, size in totals.most_common(top))


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


def _probe(window, split, wait):
    """Adds Getman's ingredients to a bare window one by one."""
    from PySide6.QtWidgets import QApplication, QLabel

    def step(name):
        wait(600)
        gc.collect()
        print(f"  + {name:34} {private_mb():6.1f} MB")

    from ui import theme
    theme.apply_theme(QApplication.instance(), "dark")
    step("dark theme (palette + QSS)")
    font = theme.mono_font(10)
    step("monospace font resolved")
    plain = QLabel("GET POST Params Headers Body Send Save Collections")
    split.addWidget(plain)
    step("label, UI font")
    mono = QLabel('{ "name": "Ann", "age": 31 }')
    mono.setFont(font)
    split.addWidget(mono)
    step("label, monospace font")
    from ui.icons import icon
    from PySide6.QtWidgets import QToolButton
    for name in ("menu", "search", "eye", "gear", "more", "close", "plus", "wrap", "copy", "download"):
        button = QToolButton()
        button.setIcon(icon(name))
        split.addWidget(button)
    step("painted icons")
    kept = QLabel("× … · — ●  (the only non-ASCII glyphs the UI uses)")
    split.addWidget(kept)
    step("label, glyphs kept in the UI")
    symbols = QLabel("☰ ⚙ ⋯ ⌕ ✕ ＋ ⟳")
    split.addWidget(symbols)
    step("label, symbol glyphs (avoided)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=0, help="fail when the busy figure exceeds this (MB)")
    parser.add_argument("--breakdown", action="store_true", help="Windows: show who owns private memory")
    parser.add_argument("--bare", action="store_true", help="baseline: an empty PySide6 window, no Getman")
    parser.add_argument("--probe", action="store_true", help="with --bare: cost of styling, fonts and symbols")
    args = parser.parse_args()
    print(f"python started:              {private_mb():6.1f} MB")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    print(f"Qt modules imported:         {private_mb():6.1f} MB")
    app = QApplication(sys.argv)
    print(f"QApplication created:        {private_mb():6.1f} MB")

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    if args.bare:
        from PySide6.QtWidgets import QMainWindow, QPlainTextEdit, QSplitter, QTreeWidget
        window = QMainWindow()
        split = QSplitter()
        split.addWidget(QTreeWidget())
        split.addWidget(QPlainTextEdit())
        window.setCentralWidget(split)
        window.resize(1360, 860)
        window.show()
        wait(1500)
        gc.collect()
        print(f"bare PySide6 window shown:   {private_mb():6.1f} MB{extra()}")
        if args.breakdown and sys.platform == "win32":
            print(windows_breakdown())
        if args.probe:
            _probe(window, split, wait)
        return 0

    from ui.main_window import MainWindow
    print(f"Getman modules imported:     {private_mb():6.1f} MB")
    window = MainWindow()
    print(f"main window constructed:     {private_mb():6.1f} MB")
    window.resize(1360, 860)
    window.show()
    wait(1500)
    gc.collect()
    idle = private_mb()
    print(f"idle after start:            {idle:6.1f} MB{extra()}")
    if args.breakdown and sys.platform == "win32":
        print(windows_breakdown())

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
    if args.breakdown and sys.platform == "win32":
        print(windows_breakdown())
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
