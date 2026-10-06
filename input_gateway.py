"""AI Composition shared plug — transport/arbitration only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, os
from urllib.parse import urlsplit

HOST=os.environ.get("HOST","0.0.0.0")
PORT=int(os.environ.get("PORT","10000"))
INTERFACE="COMPOSER_INTERFACE_V1"

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body=json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Methods","POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path != "/health":
            return self._send(404,{"status":"NOT_FOUND"})
        return self._send(200,{
            "interface_version":INTERFACE,
            "status":"PLUG_READY",
            "role":"PASS_THROUGH_ARBITER",
            "inbound_ready":True,
            "outbound_ready":True
        })

    def do_OPTIONS(self):
        self._send(204,{})

    def do_POST(self):
        path=urlsplit(self.path).path
        if path != "/plug":
            return self._send(404,{"status":"NOT_FOUND"})
        try:
            n=int(self.headers.get("Content-Length","0"))
            payload=json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(payload,dict):
                raise ValueError("INPUT_PAYLOAD_MUST_BE_OBJECT")
            if payload.get("interface_version") not in (None,INTERFACE):
                raise ValueError("INTERFACE_VERSION_INVALID")
            command=payload.get("command","compose")
            if command=="ping":
                return self._send(200,{
                    "interface_version":INTERFACE,
                    "status":"PLUG_READY",
                    "role":"PASS_THROUGH_ARBITER",
                    "inbound_ready":True,
                    "outbound_ready":True
                })
            if command!="compose":
                raise ValueError("PLUG_COMMAND_INVALID")
            # The plug arbitrates transport only. It deliberately contains no
            # composition, rendering, instruments, samples, or mixing logic.
            return self._send(200,{
                "interface_version":INTERFACE,
                "status":"HANDOFF_READY",
                "handoff_ok":True,
                "outbound_ready":True,
                "command":command,
                "request":payload
            })
        except Exception as exc:
            return self._send(400,{"status":"INPUT_ERROR","error":str(exc)})

    def log_message(self, fmt, *args):
        pass

if __name__=="__main__":
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
