#!/usr/bin/env python3
"""Local preview with the charset declared.

python -m http.server sends `text/html` without a charset and the browser
guesses — which mangles every non-ASCII character on the page. Caught twice;
this exists so it is not caught a third time.
"""
import functools, http.server, pathlib, sys

DIST = pathlib.Path(__file__).parent / "dist"


class Handler(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        t = super().guess_type(path)
        return t + "; charset=utf-8" if t and t.startswith("text/") else t


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    h = functools.partial(Handler, directory=str(DIST))
    print(f"http://127.0.0.1:{port}")
    http.server.HTTPServer(("127.0.0.1", port), h).serve_forever()
