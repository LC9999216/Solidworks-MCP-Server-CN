"""
Development launcher: watches source files and restarts server.py on changes.

Usage:
  Point claude_desktop_config.json at this file instead of server.py during development:

  {
    "mcpServers": {
      "solidworks": {
        "command": "python",
        "args": ["C:\\path\\to\\SolidWorks-MCP\\dev_server.py"]
      }
    }
  }

  Requires: pip install watchdog
"""

import subprocess
import sys
import time
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("watchdog not installed. Run: pip install watchdog", file=sys.stderr)
    sys.exit(1)

SERVER_DIR = Path(__file__).parent
SERVER_SCRIPT = SERVER_DIR / "server.py"
WATCH_PATHS = [
    SERVER_DIR / "server.py",
    SERVER_DIR / "solidworks",
]


class RestartHandler(FileSystemEventHandler):
    def __init__(self):
        self.restart_flag = False

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            print(f"[dev_server] Change detected: {event.src_path}", file=sys.stderr)
            self.restart_flag = True


def run():
    handler = RestartHandler()
    observer = Observer()
    for path in WATCH_PATHS:
        if path.exists():
            observer.schedule(handler, str(path), recursive=True)

    observer.start()
    print(f"[dev_server] Watching for changes. Serving {SERVER_SCRIPT.name}", file=sys.stderr)

    try:
        while True:
            proc = subprocess.Popen(
                [sys.executable, str(SERVER_SCRIPT)],
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )

            # Wait for the process to exit or a file change to trigger a restart
            while proc.poll() is None:
                if handler.restart_flag:
                    handler.restart_flag = False
                    print("[dev_server] Restarting server...", file=sys.stderr)
                    proc.terminate()
                    proc.wait()
                    break
                time.sleep(0.5)
            else:
                # Server exited on its own (e.g. crash) — restart it
                code = proc.returncode
                if code != 0:
                    print(f"[dev_server] Server exited with code {code}, restarting in 1s...", file=sys.stderr)
                    time.sleep(1)
    except KeyboardInterrupt:
        print("[dev_server] Shutting down.", file=sys.stderr)
        proc.terminate()
        proc.wait()
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    run()
