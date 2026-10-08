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
        finally:
            proxy.shutdown()
            fake.shutdown()
            proxy.server_close()
            fake.server_close()
            plug.UPSTREAM = previous


if __name__ == "__main__":
    unittest.main(verbosity=2)
