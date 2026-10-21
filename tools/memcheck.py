"""Memory budget check: starts Getman, exercises it like a user would and
reports the process memory the OS charges to it.

    python tools/memcheck.py              # print numbers
    python tools/memcheck.py --budget 50  # exit 1 if over 50 MB

Metric: Windows — private working set (the "Memory" column of Task Manager,
needs ``pip install psutil``); Linux — anonymous private memory (shared
library code is excluded, as on Windows); macOS — RSS (upper bound).
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


def private_mb() -> float:
    if sys.platform.startswith("linux"):
        with open("/proc/self/smaps_rollup") as f:
            for line in f:
                if line.startswith("Anonymous:"):
                    return int(line.split()[1]) / 1024
    try:
        import psutil
    except ImportError:
        sys.exit("psutil is required on this platform: pip install psutil")
    info = psutil.Process().memory_full_info()
    return (info.uss if sys.platform == "win32" else info.rss) / 1024 / 1024


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
    print(f"idle after start:            {idle:6.1f} MB")

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
    print(f"5 tabs, 40 requests sent:    {busy:6.1f} MB")
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
