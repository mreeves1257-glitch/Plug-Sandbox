import base64
import hashlib
import io
import json
import math
import sqlite3
import tempfile
from pathlib import Path
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile

import test_recordings
from server import Handler, process_record


def request_data(samples=None):
    samples = samples if samples is not None else [round(10000 * math.sin(2 * math.pi * 512 * i / 8192)) for i in range(2048)]
    payload = test_recordings.wav_bytes(samples)
    return dict(filename="test.wav", file_base64=base64.b64encode(payload).decode(), format="wav", analyze=True), payload


class OnlineTests(unittest.TestCase):
    def assert_numeric_failure_preserves_record(self, magnitude):
        original = ("sample_index,x\n" + "".join(
            f"{i},{magnitude if i % 2 else -magnitude}\n" for i in range(256))).encode()
        request = dict(filename="extreme.csv", format="csv",
                       file_base64=base64.b64encode(original).decode(),
                       csv_sample_rate_hz=8192, fft_size=256, max_frames=1)
        result = process_record(request)
        self.assertIsNone(result["report"])
        self.assertTrue(result["diagnostic_error"])
        self.assertEqual(result["scientific_review_status"], "HOLD")
        self.assertFalse(result["server_retains_record"])
        if magnitude == 1e308:
            self.assertIn("numeric range", result["diagnostic_error"])
        else:
            self.assertIn("Out of range float", result["diagnostic_error"])
        json.dumps(result, allow_nan=False)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["record_base64"]))) as archive:
            self.assertEqual(archive.read("original/extreme.csv"), original)
            self.assertNotIn("frequency-report.json", archive.namelist())
            self.assertIsNone(json.loads(archive.read("record.json"))["derivative_id"])
            manifest = json.loads(archive.read("sha256-manifest.json"))
            for name, digest in manifest.items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "evidence.sqlite"
                path.write_bytes(archive.read("evidence.sqlite"))
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute("SELECT payload FROM evidence").fetchone()[0], original)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM derivatives").fetchone()[0], 0)

    def test_arithmetic_overflow_keeps_original_downloadable(self):
        self.assert_numeric_failure_preserves_record(1e308)

    def test_nonfinite_derived_output_keeps_original_downloadable(self):
        self.assert_numeric_failure_preserves_record(1e154)

    def test_full_record_preserves_original_and_hashes(self):
        request, original = request_data()
        result = process_record(request)
        self.assertEqual(result["report"]["channels"][0]["frames"][0]["peaks"][0]["frequency_hz"], 512)
        self.assertEqual(result["scientific_review_status"], "HOLD")
        self.assertFalse(result["server_retains_record"])
        self.assertTrue(result["metadata_gaps"])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["record_base64"]))) as archive:
            self.assertEqual(archive.read("original/test.wav"), original)
            manifest = json.loads(archive.read("sha256-manifest.json"))
            for name, digest in manifest.items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
            self.assertIn("evidence.sqlite", archive.namelist())

    def test_malformed_wav_still_has_downloadable_original(self):
        original = b"not a wav file"
        result = process_record(dict(filename="bad.wav", format="wav", file_base64=base64.b64encode(original).decode()))
        self.assertIsNone(result["report"])
        self.assertTrue(result["diagnostic_error"])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["record_base64"]))) as archive:
            self.assertEqual(archive.read("original/bad.wav"), original)

    def test_csv_path_with_declared_rate(self):
        payload = b"sample_index,pressure\n" + "".join(f"{i},{math.sin(2 * math.pi * 512 * i / 8192)}\n" for i in range(2048)).encode()
        result = process_record(dict(filename="test.csv", format="csv", file_base64=base64.b64encode(payload).decode(),csv_sample_rate_hz=8192))
        self.assertEqual(result["report"]["channels"][0]["frames"][0]["peaks"][0]["frequency_hz"], 512)

    def test_csv_requires_a_rate(self):
        with self.assertRaises(ValueError):
            process_record(dict(filename="test.csv",format="csv",file_base64=base64.b64encode(b"sample_index,x\n0,1\n").decode()))

    def test_native_preservation_without_analysis(self):
        result = process_record(dict(filename="../../original.bin",format="native",file_base64=base64.b64encode(b"original bytes").decode()))
        self.assertIsNone(result["report"])
        self.assertEqual(result["filename"], "original.bin")

    def test_invalid_encoding_rejected(self):
        with self.assertRaises(ValueError):
            process_record(dict(format="wav",file_base64="invalid!"))

    def test_short_record_preserved_without_invented_analysis(self):
        request, original = request_data([0] * 10)
        result = process_record(request)
        self.assertIsNone(result["report"])
        self.assertIn("shorter",result["diagnostic_error"])

    def test_public_health_and_http_upload(self):
        server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
        worker = threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/health") as response:
                self.assertFalse(json.load(response)["physical_hardware_connected"])
            with urlopen(base + "/api/equipment-readiness") as response:
                readiness = json.load(response)
                self.assertEqual(readiness["equipment_template_count"], 24)
                self.assertEqual(readiness["live_driver_count"], 0)
                self.assertFalse(readiness["physical_hardware_connected"])
            request, _ = request_data()
            http = Request(base + "/api/process", data=json.dumps(request).encode(),headers={"Content-Type":"application/json"})
            with urlopen(http) as response:
                self.assertEqual(json.load(response)["scientific_review_status"],"HOLD")
            http = Request(base + "/api/process", data=b"{}",headers={"Content-Type":"application/json","Origin":"https://other.example"})
            with self.assertRaises(HTTPError) as raised:
                urlopen(http)
            self.assertEqual(raised.exception.code,403)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
