#!/usr/bin/env python3
"""Dev server with clean-URL fallback for HelmsMate decks.

Paths that don't resolve to a real file fall back to index.html, so deep
links like /4 keep working on refresh — a plain `python -m http.server`
would 404 on them. Also sends `Cache-Control: no-store` to dodge
heuristic caching during iteration.

Usage:
    python scripts/serve.py            # dist/ on :8000
    python scripts/serve.py 8932
    python scripts/serve.py 8932 dist
"""

import http.server
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.normpath(os.path.join(HERE, "..", "dist"))


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = super().translate_path(path)
        if not os.path.exists(p):
            p = os.path.join(self.directory, "index.html")
        return p

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    root = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ROOT
    handler = lambda *a, **kw: SPAHandler(*a, directory=root, **kw)
    with http.server.ThreadingHTTPServer(("", port), handler) as httpd:
        print(f"Serving {root} at http://127.0.0.1:{port}/ (clean-URL fallback on)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
