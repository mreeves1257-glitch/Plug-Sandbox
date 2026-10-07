"""Shared plug gateway — transport/pass-through only.

Built from the old plug's external interface, with Portal 4 and all Composer
internals deliberately excluded. The plug accepts traffic, preserves the
payload, and returns a successful handoff. It does not compose, render,
interpret Composer states, or convert downstream states into HTTP 409 errors.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import urlsplit

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "10000"))
INTERFACE = "COMPOSER_INTERFACE_V1"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path != "/health":
            return self._send(404, {"status": "NOT_FOUND"})
        return self._send(200, {
            "interface_version": INTERFACE,
            "status": "COMPOSER_READY",
            "role": "PASS_THROUGH",
            "inbound_ready": True,
            "outbound_ready": True,
            "portal4_present": False,
            "composer_embedded": False
        })

    def do_OPTIONS(self):
        self._send(204, {})

    def do_POST(self):
        path = urlsplit(self.path).path
        # Preserve the old plug's two public entry points.
        if path not in ("/plug", "/compose"):
            return self._send(404, {"status": "NOT_FOUND"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("INPUT_PAYLOAD_MUST_BE_OBJECT")

            version = payload.get("interface_version")
            if version not in (None, INTERFACE):
                raise ValueError("INTERFACE_VERSION_INVALID")

            command = payload.get("command", "compose")

            if command == "ping":
                return self._send(200, {
                    "interface_version": INTERFACE,
                    "status": "COMPOSER_READY",
                    "role": "PASS_THROUGH",
                    "inbound_ready": True,
                    "outbound_ready": True
                })

            # Pass-through boundary only:
            # - no Portal 4
            # - no Composer engine
            # - no instruments/samples/rendering
            # - no resource-state interpretation
            # - no HTTP 409 conversion
            return self._send(200, {
                "interface_version": INTERFACE,
                "status": "HANDOFF_READY",
                "handoff_ok": True,
                "inbound_ready": True,
                "outbound_ready": True,
                "entry_path": path,
                "command": command,
                "request": payload
            })

        except Exception as exc:
            return self._send(400, {
                "status": "INPUT_ERROR",
                "error": str(exc)
            })

    def log_message(self, fmt, *args):
        pass


def serve(host=HOST, port=PORT):
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
