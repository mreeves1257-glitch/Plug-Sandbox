"""Tests for the real shared plug; uses a local fake Composer, never Render."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

import input_gateway as plug


class FakeComposer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            payload = b'{"status":"BRIDGE_READY","audio_ready":false}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/missing":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/audio/no-length.wav":
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            self.wfile.write(b"RIFF" + b"Z" * 8000)
        elif self.path == "/audio/final_audio/composition_test/stereo_derivative.wav":
            contents = b"RIFF" + b"X" * (200 * 1024)
            range_header = self.headers.get("Range")
            if range_header == "bytes=0-100":
                contents = contents[:101]
                self.send_response(206)
                self.send_header("Content-Range", "bytes 0-100/204804")
            else:
                self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(contents)))
            self.end_headers()
            self.wfile.write(contents)
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        return self.do_GET()

    def log_message(self, *args):
        pass


class PlugContractTests(unittest.TestCase):
    def test_only_documented_200_bridge_ready_counts(self):
        self.assertTrue(plug._composer_gateway_ready(200, {"status": "BRIDGE_READY"}))
        self.assertFalse(plug._composer_gateway_ready(404, {"status": "BRIDGE_READY"}))
        self.assertFalse(plug._composer_gateway_ready(200, {"status": "NOT_FOUND"}))
        self.assertFalse(plug._composer_gateway_ready(503, {"status": "BRIDGE_READY"}))
        self.assertFalse(plug._composer_gateway_ready(200, {}))

    def test_audio_transfer_and_range_proxy(self):
        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeComposer)
        t1 = threading.Thread(target=fake.serve_forever, daemon=True)
        t1.start()
        previous = plug.UPSTREAM
        plug.UPSTREAM = "http://127.0.0.1:" + str(fake.server_port)
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), plug.Handler)
        t2 = threading.Thread(target=proxy.serve_forever, daemon=True)
        t2.start()
        url = "http://127.0.0.1:%s/audio/final_audio/composition_test/stereo_derivative.wav" % proxy.server_port
        try:
            with urlopen(url) as result:
                data = result.read()
                self.assertEqual(result.status, 200)
                self.assertEqual(len(data), 204804)
                self.assertEqual(data[:4], b"RIFF")
            with urlopen(Request(url, headers={"Range": "bytes=0-100"})) as result:
                self.assertEqual(result.status, 206)
                self.assertEqual(result.read(), data[:101])
                self.assertEqual(result.headers["Content-Range"], "bytes 0-100/204804")
            with urlopen("http://127.0.0.1:%s/health" % proxy.server_port) as result:
                self.assertEqual(json.load(result)["status"], "COMPOSER_READY")
            # An unknown source length must not become an incorrect zero-byte
            # response as audio flows through the pass-through plug.
            with urlopen("http://127.0.0.1:%s/audio/no-length.wav" % proxy.server_port) as result:
                self.assertIsNone(result.headers.get("Content-Length"))
                self.assertEqual(len(result.read()), 8004)
        finally:
            proxy.shutdown()
            fake.shutdown()
            proxy.server_close()
            fake.server_close()
            plug.UPSTREAM = previous


    def test_music_only_request_and_write_rejection(self):
        base = {
            "interface_version": plug.INTERFACE, "request_id": "cp-1730000000000-1",
            "source": "Control Panel", "music_engine": "AI_COMPOSITION",
            "destination": "AI Composition - Sandbox", "entry_path": "/plug",
            "command": "compose", "execute": "AICompositionEngine.run",
            "target": "INTERNAL", "mode": "normal", "genre": "New Age",
            "portal3_route": "MUSIC", "tuning_reference_hz": 440,
            "requested_at": "2026-11-18T14:00:00.000Z",
        }
        self.assertEqual(plug._music_only_request(base), base)
        for name in ("House", "Classical", "ROCK", "Afro-Latin / Afrobeats Fusion", "Chugg / #chugg", "Contemporary R&B"):
            self.assertEqual(plug._music_only_request(dict(base, genre=name))["genre"], name)
        for injected in (
            {"operation": "overwrite", "file": "ACTIVE_MASTER.json"},
            {"master_patch": {"name": "replacement"}},
            {"genre_style_packages": {"new_age.json": "modified"}},
            {"command": "update_master"},
            {"target": "EXTERNAL"},
            {"portal3_route": "SCIENCE"},
            {"execute": "os.system"},
        ):
            with self.subTest(injected=injected):
                with self.assertRaises(ValueError):
                    plug._music_only_request(dict(base, **injected))
        valid = dict(base, controlled_input={"sections": [{"genre": "House", "duration_seconds": 15}]})
        self.assertEqual(plug._music_only_request(valid)["controlled_input"]["sections"][0]["genre"], "House")
        with self.assertRaises(ValueError):
            plug._music_only_request(dict(base, controlled_input={"sections": [{"genre": "House", "duration_seconds": 15, "write": True}]}))

    def test_http_mutation_request_never_reaches_upstream(self):
        import urllib.error
        class CaptureComposer(FakeComposer):
            calls = []
            def do_POST(self):
                type(self).calls.append((self.path, json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))))
                body = b'{"status":"COMPOSITION_ACCEPTED"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), CaptureComposer)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        previous = plug.UPSTREAM
        plug.UPSTREAM = "http://127.0.0.1:" + str(upstream.server_port)
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), plug.Handler)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        payload = {
            "interface_version": plug.INTERFACE, "request_id": "cp-1730000000000-2",
            "source": "Control Panel", "music_engine": "AI_COMPOSITION",
            "destination": "AI Composition - Sandbox", "entry_path": "/plug",
            "command": "compose", "execute": "AICompositionEngine.run",
            "target": "INTERNAL", "mode": "normal", "genre": "House",
            "portal3_route": "MUSIC", "tuning_reference_hz": 432,
            "requested_at": "2026-11-18T14:00:00.000Z",
        }
        def post(data, route="/plug"):
            return urlopen(Request("http://127.0.0.1:%s%s" % (proxy.server_port, route),
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST"))
        try:
            with post(payload) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(CaptureComposer.calls, [("/compose", payload)])
            for route in ("/plug", "/compose"):
                with self.assertRaises(urllib.error.HTTPError) as blocked:
                    post(dict(payload, file_write={"path": "ACTIVE_MASTER.json"}), route)
                self.assertEqual(blocked.exception.code, 400)
                self.assertIn("CONTROL_PANEL_UNAUTHORIZED_FIELD", blocked.exception.read().decode())
            self.assertEqual(len(CaptureComposer.calls), 1)
        finally:
            proxy.shutdown()
            upstream.shutdown()
            proxy.server_close()
            upstream.server_close()
            plug.UPSTREAM = previous



if __name__ == "__main__":
    unittest.main(verbosity=2)
