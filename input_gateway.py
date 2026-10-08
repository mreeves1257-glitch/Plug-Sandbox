"""Shared plug gateway — external pass-through only.

No Portal 4. No embedded Composer. No instruments, samples, rendering, or
composition logic. This service relays Control Panel traffic to the separate
Composer service and relays Composer responses/audio back to the panel.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import urllib.error
import urllib.request
import threading
import time
from urllib.parse import urlsplit, urljoin

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "10000"))
INTERFACE = "COMPOSER_INTERFACE_V1"
UPSTREAM = os.environ.get("COMPOSER_URL", "").strip().rstrip("/")
# The phone panel permits 405 seconds; keep the default plug wait shorter
# than that but long enough for a full composition. An explicit Render env
# setting takes precedence and must still be checked on the deployed service.
TIMEOUT = float(os.environ.get("COMPOSER_TIMEOUT_SECONDS", "390"))


def upstream_url(path):
    if not UPSTREAM:
        raise RuntimeError("COMPOSER_URL_NOT_CONFIGURED")
    return urljoin(UPSTREAM + "/", path.lstrip("/"))


def _composer_gateway_ready(http_status, state):
    """Never mistake HTTP 404/redirect/HTML for Composer readiness.

    The Composer's preserved /health route returns 200 and BRIDGE_READY.
    This verifies the gateway, not the availability of all instrument banks.
    """
    return (http_status == 200 and isinstance(state, dict)
            and state.get("status") == "BRIDGE_READY")


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _proxy(self, method, target_path, body=None, content_type=None):
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        if self.headers.get("Range"):
            headers["Range"] = self.headers["Range"]
        req = urllib.request.Request(
            upstream_url(target_path),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            response = exc

        is_audio = target_path.startswith("/audio/")
        # Audio must be forwarded in bounded chunks, not fully buffered in RAM.
        data = b"" if method == "HEAD" or is_audio else response.read()
        preview = "[streamed audio]" if is_audio else data[:4000].decode("utf-8", errors="replace")
        print(f"PLUG RELAY method={method} target={target_path} upstream_status={response.status} body={preview}", flush=True)
        self.send_response(response.status)
        for key in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
            value = response.headers.get(key)
            if value:
                self.send_header(key, value)
        if not response.headers.get("Content-Length") and not is_audio:
            # JSON responses are already buffered. For streamed WAV without
            # an upstream length, let HTTP/1.0 close terminate the response;
            # do not incorrectly advertise zero bytes.
            self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        if method != "HEAD":
            if is_audio:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            elif data:
                self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            if not UPSTREAM:
                return self._json(503, {
                    "interface_version": INTERFACE,
                    "status": "COMPOSER_UPSTREAM_NOT_CONFIGURED",
                    "inbound_ready": True,
                    "outbound_ready": False,
                })
            try:
                req = urllib.request.Request(upstream_url("/health"), method="GET")
                try:
                    response = urllib.request.urlopen(req, timeout=10)
                except urllib.error.HTTPError as exc:
                    response = exc
                raw = response.read()
                try:
                    state = json.loads(raw.decode("utf-8"))
                except Exception:
                    state = {}
                ready = _composer_gateway_ready(response.status, state)
                return self._json(200 if ready else 503, {
                    "interface_version": INTERFACE,
                    "status": "COMPOSER_READY" if ready else "COMPOSER_UNAVAILABLE",
                    "role": "PASS_THROUGH",
                    "inbound_ready": True,
                    "outbound_ready": ready,
                    "upstream_status": response.status,
                    "upstream": state,
                })
            except Exception as exc:
                return self._json(503, {
                    "interface_version": INTERFACE,
                    "status": "COMPOSER_UNAVAILABLE",
                    "inbound_ready": True,
                    "outbound_ready": False,
                    "error": str(exc),
                })

        if path.startswith("/audio/"):
            target = path
            if urlsplit(self.path).query:
                target += "?" + urlsplit(self.path).query
            return self._proxy("GET", target)

        return self._json(404, {"status": "NOT_FOUND"})

    def do_HEAD(self):
        path = urlsplit(self.path).path
        if path.startswith("/audio/"):
            target = path
            if urlsplit(self.path).query:
                target += "?" + urlsplit(self.path).query
            return self._proxy("HEAD", target)
        return self._json(404, {"status": "NOT_FOUND"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/plug", "/compose"):
            return self._json(404, {"status": "NOT_FOUND"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("INPUT_PAYLOAD_MUST_BE_OBJECT")
            if payload.get("interface_version") not in (None, INTERFACE):
                raise ValueError("INTERFACE_VERSION_INVALID")

            print(f"PLUG REQUEST path={path} request_id={payload.get('request_id')} genre={payload.get('genre')} command={payload.get('command')}", flush=True)
            if payload.get("command") == "ping":
                return self.do_GET_health()

            return self._proxy(
                "POST",
                "/compose",
                body=body,
                content_type=self.headers.get("Content-Type", "application/json"),
            )
        except Exception as exc:
            return self._json(400, {"status": "INPUT_ERROR", "error": str(exc)})

    def do_GET_health(self):
        if not UPSTREAM:
            return self._json(503, {
                "interface_version": INTERFACE,
                "status": "COMPOSER_UPSTREAM_NOT_CONFIGURED",
                "inbound_ready": True,
                "outbound_ready": False,
            })
        try:
            req = urllib.request.Request(upstream_url("/health"), method="GET")
            try:
                response = urllib.request.urlopen(req, timeout=10)
            except urllib.error.HTTPError as exc:
                response = exc
            raw = response.read()
            try:
                state = json.loads(raw.decode("utf-8"))
            except Exception:
                state = {}
            ready = _composer_gateway_ready(response.status, state)
            return self._json(200 if ready else 503, {
                "interface_version": INTERFACE,
                "status": "COMPOSER_READY" if ready else "COMPOSER_UNAVAILABLE",
                "role": "PASS_THROUGH",
                "inbound_ready": True,
                "outbound_ready": ready,
                "upstream_status": response.status,
                "upstream": state,
            })
        except Exception as exc:
            return self._json(503, {
                "interface_version": INTERFACE,
                "status": "COMPOSER_UNAVAILABLE",
                "inbound_ready": True,
                "outbound_ready": False,
                "error": str(exc),
            })

    def log_message(self, fmt, *args):
        pass


def _startup_selftest():
    if os.environ.get("PLUG_STARTUP_SELFTEST", "").strip() != "1":
        return
    time.sleep(2)
    payload = {
        "interface_version": INTERFACE,
        "request_id": "plug-selftest-" + str(int(time.time())),
        "source": "Plug Self Test",
        "music_engine": "AI_COMPOSITION",
        "destination": "AI Composition - Sandbox",
        "entry_path": "/plug",
        "command": "compose",
        "execute": "AICompositionEngine.run",
        "target": "INTERNAL",
        "mode": "normal",
        "genre": "ROCK",
        "portal3_route": "MUSIC",
        "tuning_reference_hz": 440,
    }
    body = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(
            upstream_url("/compose"),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            response = exc
        raw = response.read()
        preview = raw[:8000].decode("utf-8", errors="replace")
        print(f"PLUG SELFTEST upstream={UPSTREAM} status={response.status} body={preview}", flush=True)
    except Exception as exc:
        print(f"PLUG SELFTEST ERROR upstream={UPSTREAM or 'UNSET'} error={exc}", flush=True)


def serve(host=HOST, port=PORT):
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"PLUG START host={host} port={port} upstream_configured={bool(UPSTREAM)}", flush=True)
    threading.Thread(target=_startup_selftest, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    serve()
