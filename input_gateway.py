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



# No Control Panel path may update Composer files, genre packages, or master state.
# Enforce this at the shared plug, not only in downloadable browser JavaScript.
PANEL_FIELDS = frozenset({
    "interface_version", "request_id", "source", "music_engine",
    "destination", "entry_path", "command", "execute", "target",
    "mode", "genre", "portal3_route", "tuning_reference_hz",
    "requested_at", "controlled_input",
})
PANEL_FIXED = {
    "interface_version": INTERFACE,
    "source": "Control Panel",
    "music_engine": "AI_COMPOSITION",
    "destination": "AI Composition - Sandbox",
    "entry_path": "/plug",
    "command": "compose",
    "execute": "AICompositionEngine.run",
    "target": "INTERNAL",
}
MAX_PANEL_REQUEST_BYTES = 16384


def _genre_text(value):
    # Slash, #, Unicode and ampersands are valid in the 55 official genre names.
    return (isinstance(value, str) and 0 < len(value) <= 120
            and value.strip() == value
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _checked_controlled_input(value):
    # User-controlled compositions may select musical sections, never files/code.
    import math
    if not isinstance(value, dict):
        raise ValueError("CONTROLLED_INPUT_INVALID")
    allowed = {"saved_profile_id", "region", "source_provenance", "sections"}
    if set(value) - allowed:
        raise ValueError("CONTROLLED_INPUT_UNAUTHORIZED_FIELD")
    checked = {}
    for name in ("saved_profile_id", "region", "source_provenance"):
        if name in value:
            txt = value[name]
            if not isinstance(txt, str) or not 0 < len(txt) <= 160 or any(ord(c) < 32 for c in txt):
                raise ValueError("CONTROLLED_INPUT_FIELD_INVALID:" + name)
            checked[name] = txt
    if "sections" in value:
        sections = value["sections"]
        if not isinstance(sections, list) or not 0 < len(sections) <= 8:
            raise ValueError("CONTROLLED_SECTIONS_INVALID")
        result = []
        for section in sections:
            if not isinstance(section, dict) or set(section) != {"genre", "duration_seconds"}:
                raise ValueError("CONTROLLED_SECTION_UNAUTHORIZED_FIELD")
            if not _genre_text(section["genre"]):
                raise ValueError("CONTROLLED_SECTION_GENRE_INVALID")
            duration = section["duration_seconds"]
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 1 <= duration <= 3600:
                raise ValueError("CONTROLLED_SECTION_DURATION_INVALID")
            result.append({"genre": section["genre"], "duration_seconds": duration})
        checked["sections"] = result
    return checked


def _music_only_request(payload):
    """Allowlist the complete request and reconstruct it before forwarding."""
    import re
    if not isinstance(payload, dict):
        raise ValueError("INPUT_PAYLOAD_MUST_BE_OBJECT")
    if set(payload) - PANEL_FIELDS:
        raise ValueError("CONTROL_PANEL_UNAUTHORIZED_FIELD")
    for key, expected in PANEL_FIXED.items():
        if payload.get(key) != expected:
            raise ValueError("CONTROL_PANEL_BOUNDARY_MISMATCH:" + key)
    if not _genre_text(payload.get("genre")):
        raise ValueError("CONTROL_PANEL_GENRE_INVALID")
    if payload.get("portal3_route") not in ("MUSIC", "BOTH"):
        raise ValueError("CONTROL_PANEL_ROUTE_NOT_MUSIC")
    if payload.get("mode") not in ("normal", "quick"):
        raise ValueError("CONTROL_PANEL_MODE_INVALID")
    tuning = payload.get("tuning_reference_hz")
    if type(tuning) not in (int, float) or tuning not in (432, 440):
        raise ValueError("CONTROL_PANEL_TUNING_INVALID")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"cp-[0-9]+-[0-9]+", request_id):
        raise ValueError("CONTROL_PANEL_REQUEST_ID_INVALID")
    requested_at = payload.get("requested_at")
    if (not isinstance(requested_at, str) or
            not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", requested_at)):
        raise ValueError("CONTROL_PANEL_TIMESTAMP_INVALID")
    safe = {key: payload[key] for key in PANEL_FIXED}
    for key in ("request_id", "genre", "portal3_route", "mode", "tuning_reference_hz", "requested_at"):
        safe[key] = payload[key]
    if "controlled_input" in payload:
        safe["controlled_input"] = _checked_controlled_input(payload["controlled_input"])
    return safe



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
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                return self._json(415, {"status": "INPUT_ERROR", "error": "JSON_CONTENT_TYPE_REQUIRED"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_PANEL_REQUEST_BYTES:
                return self._json(413, {"status": "INPUT_ERROR", "error": "CONTROL_PANEL_REQUEST_SIZE_INVALID"})
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if isinstance(payload, dict) and payload.get("command") == "ping":
                if set(payload) not in ({"command"}, {"command", "interface_version"}):
                    raise ValueError("CONTROL_PANEL_PING_FIELDS_BLOCKED")
                if payload.get("interface_version", INTERFACE) != INTERFACE:
                    raise ValueError("INTERFACE_VERSION_INVALID")
                return self.do_GET_health()
            safe_payload = _music_only_request(payload)
            body = json.dumps(safe_payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            print(f"PLUG REQUEST path={path} request_id={safe_payload['request_id']} genre={safe_payload['genre']} command=compose", flush=True)
            return self._proxy(
                "POST",
                "/compose",
                body=body,
                content_type="application/json",
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
