"""Local static-only preview; never loads .env or opens the application database."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parent / "static"


class PreviewHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.path = "/index.html"
        elif path.startswith("/static/"):
            self.path = path[len("/static"):]
        else:
            self.send_error(404)
            return
        super().do_GET()

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), partial(PreviewHandler, directory=str(STATIC)))
    print("Предварительный просмотр: http://127.0.0.1:8000 (Ctrl+C — остановить)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
