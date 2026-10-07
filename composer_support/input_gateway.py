"""Render-facing gateway for the preserved October 5 Composer.
Composition engine stays unchanged. This boundary completes the already-preserved
stems -> Scene 009 -> Object Master 006 -> stereo listening derivative handoff.
"""
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
from urllib.parse import quote,unquote,urlsplit
import threading
from engine import AICompositionEngine
from output_handoff import OUT
from spatial_finalizer import finalize_spatial_master

COMPOSE_LOCK=threading.Lock()

def compose_request(payload):
    if not isinstance(payload,dict): raise ValueError("INPUT_PAYLOAD_MUST_BE_OBJECT")
    genre=payload.get("genre")
    if not isinstance(genre,str) or not genre.strip(): raise ValueError("INPUT_GENRE_REQUIRED")
    target=payload.get("target","INTERNAL"); mode=payload.get("mode","normal")
    if mode not in ("normal","quick"): raise ValueError("INPUT_MODE_INVALID")
    if not isinstance(target,str): raise ValueError("INPUT_TARGET_INVALID")
    with COMPOSE_LOCK:
        result=AICompositionEngine().run(genre.strip(),target,mode)
    if result.get("status")=="AUDIO_STEMS_READY_MASTER_REQUIRED":
        try:
            result["audio_render"]=finalize_spatial_master(result,OUT)
            result["audio_rendered"]=True; result["status"]="AUDIO_RENDER_PASS"; result["reason"]=None
            result.setdefault("order",[]).append("SCENE_009_OBJECT_MASTER_006")
        except Exception as exc:
            result["audio_render"]={"status":"AUDIO_RENDER_FAILED","audio_rendered":False,"reason":"SPATIAL_MASTER_FAILED:"+str(exc)}
            result["audio_rendered"]=False; result["status"]="AUDIO_RENDER_FAILED"; result["reason"]=result["audio_render"]["reason"]
    def audio_urls(value):
        if isinstance(value,dict):
            value={k:audio_urls(v) for k,v in value.items()}
            if value.get("wav_path"):
                try:
                    rel=Path(value["wav_path"]).resolve().relative_to(OUT.resolve())
                    value["audio_url"]="/audio/"+quote(rel.as_posix(),safe="/")
                except ValueError: pass
        elif isinstance(value,list): value=[audio_urls(v) for v in value]
        return value
    return {"status":result.get("status"),"genre":result.get("genre",genre.strip()),"reason":result.get("reason"),
            "stage":result.get("stage"),"audio_rendered":result.get("audio_rendered",False),
            "output_handoff":result.get("output_handoff"),"audio_resource_preflight":result.get("audio_resource_preflight"),
            "audio_render":audio_urls(result.get("audio_render")),"resource_requirements":result.get("resource_requirements",[])}

class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Methods","POST, GET, HEAD, OPTIONS")
    def _send(self,code,payload):
        body=json.dumps(payload).encode("utf-8"); self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body))); self._cors(); self.end_headers()
        if self.command!="HEAD": self.wfile.write(body)
    def _audio(self,head=False):
        path=urlsplit(self.path).path
        file=(OUT/unquote(path[len("/audio/"):])).resolve()
        try: file.relative_to(OUT.resolve())
        except ValueError: return self._send(403,{"status":"FORBIDDEN"})
        if file.suffix.lower()!=".wav" or not file.is_file(): return self._send(404,{"status":"AUDIO_NOT_FOUND"})
        size=file.stat().st_size; start=0; end=size-1; partial=False; range_header=self.headers.get("Range")
        if range_header:
            import re
            match=re.fullmatch(r"bytes=(\d*)-(\d*)",range_header)
            if not match or not any(match.groups()): return self._send(416,{"status":"INVALID_RANGE"})
            a,b=match.groups()
            if a: start=int(a); end=min(int(b),end) if b else end
            else: start=max(0,size-int(b))
            if start>end or start>=size: return self._send(416,{"status":"INVALID_RANGE"})
            partial=True
        self.send_response(206 if partial else 200); self.send_header("Content-Type","audio/wav"); self._cors()
        self.send_header("Accept-Ranges","bytes"); self.send_header("Content-Length",str(end-start+1))
        if partial: self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:return
        with file.open("rb") as stream:
            stream.seek(start); remaining=end-start+1
            while remaining:
                chunk=stream.read(min(65536,remaining))
                if not chunk:break
                self.wfile.write(chunk); remaining-=len(chunk)
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=="/health": return self._send(200,{"status":"COMPOSER_READY","outbound_ready":True,"audio_ready":True,"fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"})
        if path.startswith("/audio/"): return self._audio(False)
        return self._send(404,{"status":"NOT_FOUND"})
    def do_HEAD(self):
        path=urlsplit(self.path).path
        if path.startswith("/audio/"): return self._audio(True)
        if path=="/health": return self._send(200,{"status":"COMPOSER_READY","outbound_ready":True,"audio_ready":True})
        return self._send(404,{"status":"NOT_FOUND"})
    def do_OPTIONS(self): self._send(204,{})
    def do_POST(self):
        if urlsplit(self.path).path!="/compose": return self._send(404,{"status":"NOT_FOUND"})
        try:
            n=int(self.headers.get("Content-Length","0")); payload=json.loads(self.rfile.read(n) or b"{}"); result=compose_request(payload)
            if result.get("audio_rendered"): return self._send(200,result)
            status=result.get("status")
            if status in ("PERFORMANCE_READY_RESOURCE_REQUIRED","AUDIO_RENDER_RESOURCE_REQUIRED"):
                return self._send(409,{**result,"outbound_ready":True,"delivery_status":"RESOURCE_REQUIRED","fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"})
            if status=="AUDIO_STEMS_READY_MASTER_REQUIRED":
                return self._send(409,{**result,"outbound_ready":True,"delivery_status":"MASTER_REQUIRED","fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"})
            if status in ("AUDIO_RENDER_FAILED","AUDIO_RENDER_BLOCKED"):
                return self._send(503,{**result,"outbound_ready":True,"delivery_status":"AUDIO_UNAVAILABLE","fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"})
            if result.get("reason")=="CONTROLLED_INPUT_REQUIRED":
                return self._send(409,{**result,"outbound_ready":True,"delivery_status":"INPUT_REQUIRED","fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"})
            return self._send(422,{**result,"outbound_ready":True,"delivery_status":"COMPOSITION_BLOCKED","fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"})
        except Exception as exc:
            self._send(400,{"status":"INPUT_ERROR","error":str(exc)})
    def log_message(self,fmt,*args): pass