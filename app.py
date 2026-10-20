"""Start the DocScan web app.

    python app.py                  # opens http://127.0.0.1:8000 in your browser
    python app.py --port 8080 --no-browser
    python app.py --host 0.0.0.0   # reachable from your phone on the same Wi-Fi (camera needs HTTPS there)
"""

import argparse
import os
import socket
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)  # samples/ and outputs/ are relative to the project folder

from werkzeug.serving import make_server  # noqa: E402

from webapp.server import app  # noqa: E402


def serve(host: str, port: int):
    make_server(host, port, app, threaded=True).serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    # Browsers resolve "localhost" to the IPv6 address ::1 first. If nothing listens
    # there, every request waits for a fallback to 127.0.0.1 (very slow on Windows),
    # so for local use we listen on both.
    if args.host == "127.0.0.1" and socket.has_ipv6:
        try:
            ipv6 = make_server("::1", args.port, app, threaded=True)
            threading.Thread(target=ipv6.serve_forever, daemon=True).start()
        except OSError:
            pass  # IPv6 disabled on this machine - IPv4 alone is fine

    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    print(f"\n  DocScan is running at {url}\n  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        serve(args.host, args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
