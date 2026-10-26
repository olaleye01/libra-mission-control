"""Libra's sole HTTP listener. Start with: python3 server/server.py."""

import argparse
import hashlib
import hmac
import importlib
import json
import logging
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

if __name__ == "__main__":
    sys.modules.setdefault("server", sys.modules["__main__"])

from auth import Auth
from core import ApiError
from store import Store

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 8 * 1024 * 1024
ASSETS = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/styles.css": "styles.css"}


class Application:
    def __init__(self, data_dir, source_dir=None):
        self.store = Store(data_dir)
        self.auth = Auth(self.store)
        self.source_dir = Path(source_dir or ROOT / "imports" / "sources").resolve()
        self.routes = []
        for module in ("auth", "clients", "imports", "shipments"):
            importlib.import_module(module).register(self.route, ApiError)

    def route(self, method, path, public=False):
        def decorator(function):
            pattern = re.sub(r"<([a-z]+)>", r"(?P<\1>[^/]+)", path)
            self.routes.append((method, re.compile("^" + pattern + "$"), function, public))
            return function
        return decorator

    def sources(self):
        sources = []
        if self.source_dir.is_dir():
            for path in sorted(self.source_dir.glob("*.csv")):
                if path.is_symlink() or path.stat().st_size > 5 * 1024 * 1024:
                    continue
                sources.append({"id": hashlib.sha256(path.read_bytes()).hexdigest(),
                                "filename": path.name, "size": path.stat().st_size,
                                "mapping": "gzi-v1", "client": "GZI"})
        return sources


class Handler(BaseHTTPRequestHandler):
    server_version = "Libra/0.1"

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        # Request lines can contain private job searches; keep them out of access logs.
        logging.info("HTTP %s %s", self.command, getattr(self, "response_status", "-"))

    def send(self, status, data, content_type="application/json; charset=utf-8"):
        if isinstance(data, dict):
            data = json.dumps({"ok": status < 400, **data}, ensure_ascii=False).encode()
        self.response_status = status
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in self.extra_headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self):
        self.extra_headers = {}
        try:
            expected_port = self.server.server_address[1]
            host = urlsplit("http://" + self.headers.get("Host", ""))
            if host.hostname not in ("127.0.0.1", "localhost") or host.port != expected_port:
                raise ApiError(403, "Local access only. Use the printed loopback URL.")
            origin = self.headers.get("Origin")
            if origin:
                supplied = urlsplit(origin)
                if supplied.scheme != "http" or supplied.hostname != host.hostname or supplied.port != expected_port:
                    raise ApiError(403, "Cross-origin request refused.")
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            self.session = self.app.auth.session(self.headers)
            if path in ASSETS:
                if self.command != "GET":
                    self.extra_headers["Allow"] = "GET"
                    raise ApiError(405, "Method not allowed.")
                asset = ROOT / "frontend" / ASSETS[path]
                if not asset.is_file():
                    raise ApiError(503, "Frontend is unavailable.")
                mime = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
                self.send(200, asset.read_bytes(), mime + "; charset=utf-8")
                return
            candidates = [(m, p.match(path), fn, public) for m, p, fn, public in self.app.routes if p.fullmatch(path)]
            if not candidates:
                raise ApiError(404, "Route not found.")
            matched = next((x for x in candidates if x[0] == self.command), None)
            if not matched:
                self.extra_headers["Allow"] = ", ".join(sorted({x[0] for x in candidates}))
                raise ApiError(405, "Method not allowed.")
            _, match, handler, public = matched
            if not public and not self.session:
                raise ApiError(401, "Sign in to access shipment records.")
            if self.command == "POST" and not public:
                csrf = self.headers.get("X-CSRF-Token", "")
                if not hmac.compare_digest(csrf, self.session["csrf"]):
                    raise ApiError(403, "Session verification failed. Refresh and try again.")
            body = {}
            if self.command == "POST":
                if self.headers.get("Transfer-Encoding"):
                    raise ApiError(400, "Chunked requests are not supported.")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise ApiError(400, "Invalid content length.")
                if length < 0 or length > MAX_BODY:
                    self.close_connection = True
                    raise ApiError(413, "Request exceeds the 8 MB request limit.")
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ApiError(415, "Use application/json.")
                try:
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError):
                    raise ApiError(400, "Invalid JSON.")
                if not isinstance(body, dict):
                    raise ApiError(400, "JSON body must be an object.")
            self.path_params = match.groupdict()
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            self.send(200, handler(self, query, body))
        except ApiError as exc:
            self.send(exc.status, {"error": exc.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception("Application request failed")
            self.send(500, {"error": "The request could not be completed. See the local server log."})

    do_GET = dispatch
    do_POST = dispatch
    do_DELETE = dispatch
    do_PUT = dispatch


def make_server(data_dir, port=8800, source_dir=None):
    app = Application(data_dir, source_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.app = app
    httpd.daemon_threads = True
    return httpd


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Libra Mission Control — local test workspace")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        httpd = make_server(args.data_dir, args.port)
    except OSError as exc:
        parser.exit(1, f"Could not start local server: {exc}\n")
    print(f"Libra Mission Control: http://127.0.0.1:{httpd.server_address[1]}", flush=True)
    print("TEST workspace · notifications disabled · Hermes not connected", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
