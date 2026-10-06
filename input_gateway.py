"""AI Composition shared plug — transport/arbitration only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

HOST=os.environ.get("HOST","0.0.0.0")
PORT=int(os.environ.get("PORT","10000"))
INTERFACE="COMPOSER_INTERFACE_V1"
COMPOSER_URL=os.environ.get("AI_COMPOSITION_URL","http://127.0.0.1:8766/compose")
TIMEOUT=float(os.environ.get("AI_COMPOSITION_TIMEOUT","125"))

class Handler(BaseHTTPRequestHandler):
    def _headers(self, code, content_type="application/json; charset=utf-8", length=None):
        self.send_response(code)
        self.send_header("Content-Type",content_type)
        if length is not None:self.send_header("Content-Length",str(length))
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Methods","POST, GET, OPTIONS")
        self.end_headers()

    def _send(self, code, payload):
        body=json.dumps(payload).encode("utf-8")
        self._headers(code,length=len(body));self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path!="/health":return self._send(404,{"status":"NOT_FOUND"})
        return self._send(200,{"interface_version":INTERFACE,"status":"PLUG_READY","role":"PASS_THROUGH_ARBITER","inbound_ready":True,"outbound_ready":True,"composer_path":"/compose"})

    def do_OPTIONS(self):self._send(204,{})

    def do_POST(self):
        if urlsplit(self.path).path!="/plug":return self._send(404,{"status":"NOT_FOUND"})
        try:
            n=int(self.headers.get("Content-Length","0"))
            payload=json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(payload,dict):raise ValueError("INPUT_PAYLOAD_MUST_BE_OBJECT")
            if payload.get("interface_version") not in (None,INTERFACE):raise ValueError("INTERFACE_VERSION_INVALID")
            if payload.get("command","compose")=="ping":
                return self._send(200,{"interface_version":INTERFACE,"status":"PLUG_READY","role":"PASS_THROUGH_ARBITER","inbound_ready":True,"outbound_ready":True})
            if payload.get("command","compose")!="compose":raise ValueError("PLUG_COMMAND_INVALID")
            outgoing=dict(payload);outgoing.pop("interface_version",None)
            data=json.dumps(outgoing).encode("utf-8")
            req=Request(COMPOSER_URL,data=data,headers={"Content-Type":"application/json"},method="POST")
            try:
                with urlopen(req,timeout=TIMEOUT) as response:
                    body=response.read()
                    ctype=response.headers.get("Content-Type","application/json")
                    self._headers(response.status,ctype,len(body));self.wfile.write(body)
            except HTTPError as exc:
                body=exc.read()
                ctype=exc.headers.get("Content-Type","application/json")
                self._headers(exc.code,ctype,len(body));self.wfile.write(body)
            except URLError as exc:
                self._send(502,{"status":"COMPOSER_CONNECTION_ERROR","error":str(exc.reason)})
        except Exception as exc:
            self._send(400,{"status":"INPUT_ERROR","error":str(exc)})

    def log_message(self,fmt,*args):pass

if __name__=="__main__":
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
