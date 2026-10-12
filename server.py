"""Separate stateless online Science-Sandbox recording service."""
import base64
import csv
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import wave
import zipfile

from frequency_analysis import analyze_recording
from recording_adapters import CsvFileAdapter, WavFileAdapter, decode_wav
from science_plug import FileImportAdapter, SciencePlug
from equipment_readiness import preparation_status

APP_VERSION = "science-online-1.0.1"
MAX_UPLOAD = 10 * 1024 * 1024
MAX_REQUEST = 16 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
WORKER = threading.BoundedSemaphore(1)


def process_record(request):
    if not isinstance(request, dict):
        raise ValueError("Request must be a JSON object")
    fmt = request.get("format")
    if fmt not in {"native", "wav", "csv"}:
        raise ValueError("Choose native, WAV, or CSV format")
    encoded = request.get("file_base64")
    if not isinstance(encoded, str):
        raise ValueError("Recording bytes are required")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise ValueError("Recording encoding is invalid") from error
    if not payload or len(payload) > MAX_UPLOAD:
        raise ValueError("Choose a nonempty recording up to 10 MB")
    name = request.get("filename", "recording.dat")
    if not isinstance(name, str):
        raise ValueError("Invalid filename")
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if c.isalnum() or c in "._-")[:100]
    if not name or name in {".", ".."}:
        name = "recording.dat"
    metadata = request.get("metadata")
    if metadata is None:
        metadata = dict(mode="FILE_IMPORT", run_id=None, experiment_id=None,
                        component_id=None, source_fingerprint=hashlib.sha256(payload).hexdigest(),
                        captured_at=None, device=dict(manufacturer=None, model=None, asset_id=None),
                        timing=dict(clock_source=None, method=None), channels=[],
                        actual_conditions=["Existing file uploaded; physical acquisition conditions not supplied"], deviations=[])
        if fmt == "wav":
            try:
                decoded = decode_wav(payload)
                metadata["channels"] = [dict(id=f"channel_{i + 1}", quantity="digital_audio",
                    native_units="PCM_COUNT", engineering_units="PCM_COUNT", scale=1.0, offset=0.0,
                    sample_rate_hz=decoded["sample_rate_hz"]) for i in range(len(decoded["samples"]))]
            except (ValueError, wave.Error, EOFError):
                pass  # The original is still preserved by the format adapter.
        elif fmt == "csv":
            rate = request.get("csv_sample_rate_hz")
            if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not 0 < rate <= 10_000_000:
                raise ValueError("Enter the CSV recording's actual sample rate in Hz")
            try:
                header = next(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
            except (UnicodeError, StopIteration):
                header = []
            if header and header[0] == "sample_index":
                metadata["channels"] = [dict(id=label, quantity="unspecified_sampled_quantity",
                    native_units="native values (units unspecified)", engineering_units="native values (units unspecified)",
                    scale=1.0, offset=0.0, sample_rate_hz=rate) for label in header[1:]]
    if not isinstance(metadata, dict):
        raise ValueError("Instrument metadata must be a JSON object")
    metadata = json.loads(json.dumps(metadata, allow_nan=False))
    if not isinstance(metadata.get("channels", []), list) or len(metadata.get("channels", [])) > 8:
        raise ValueError("This online version supports up to eight mapped channels")
    if fmt == "wav":
        try:
            with wave.open(io.BytesIO(payload), "rb") as recording:
                if recording.getnchannels() > 8:
                    raise ValueError("This online version supports up to eight channels")
        except (wave.Error, EOFError):
            pass
    metadata["uploaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fft_size = request.get("fft_size", 1024)
    max_frames = request.get("max_frames", 64)
    if not isinstance(fft_size, int) or isinstance(fft_size, bool) or fft_size not in (256, 512, 1024, 2048, 4096, 8192, 16384):
        raise ValueError("Unsupported analysis window size")
    if not isinstance(max_frames, int) or isinstance(max_frames, bool) or not 1 <= max_frames <= 128:
        raise ValueError("Analysis window limit must be between 1 and 128")
    if not isinstance(request.get("analyze", True), bool):
        raise ValueError("Invalid analysis selection")
    report = None
    diagnostic_error = None
    derivative_id = None
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp) / name
        source.write_bytes(payload)
        plug = SciencePlug(Path(temp) / "evidence.sqlite")
        try:
            adapter = {"native": FileImportAdapter, "wav": WavFileAdapter, "csv": CsvFileAdapter}[fmt](source, metadata)
            plug.register(adapter)
            identifier = plug.capture(adapter.adapter_id)
            original, record = plug.load(identifier)
            if request.get("analyze", True) and fmt != "native":
                try:
                    candidate = analyze_recording(original, record, fft_size=fft_size, max_frames=max_frames)
                    # Publish only after the complete derivative is finite, serializable
                    # and saved. Failed analysis must still export the original evidence.
                    derivative_id = plug.save_derivative(identifier, candidate)
                    report = candidate
                except ArithmeticError:
                    diagnostic_error = "Diagnostic arithmetic exceeded the supported numeric range; original evidence is preserved."
                except (ValueError, wave.Error, EOFError, UnicodeError) as error:
                    diagnostic_error = str(error)
        finally:
            plug.close()
        # SQLite is a portable evidence copy inside the downloadable record, not server retention.
        files = {f"original/{name}": original,
                 "metadata.json": json.dumps(record, indent=2, allow_nan=False).encode(),
                 "evidence.sqlite": (Path(temp) / "evidence.sqlite").read_bytes()}
        if report is not None:
            files["frequency-report.json"] = json.dumps(report, indent=2, allow_nan=False).encode()
        note = dict(project="Sound, Vibration, Pattern & Consciousness",parent="Science-Sandbox",
                    app_version=APP_VERSION, import_id=identifier, derivative_id=derivative_id,
                    saved_at=record["uploaded_at"], scientific_review_status="HOLD",
                    server_retains_record=False, diagnostic_error=diagnostic_error)
        files["record.json"] = json.dumps(note, indent=2).encode()
        files["READ-ME.txt"] = ("Science-Sandbox recording record\n\nOriginal bytes are in original/. "
            "Metadata and diagnostic frequency results remain separate. evidence.sqlite contains the same "
            "raw import and any derived diagnostic report. Download this record to preserve it; this service "
            "does not retain uploads. Physical equipment and calibration have not been verified by this "
            "file analysis. Scientific review status: HOLD.\n").encode()
        manifest = {path: hashlib.sha256(content).hexdigest() for path, content in files.items()}
        files["sha256-manifest.json"] = json.dumps(manifest, indent=2).encode()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
            for path, content in files.items():
                zipped.writestr(path, content)
    return dict(app_version=APP_VERSION, import_id=identifier, filename=name, original_sha256=manifest[f"original/{name}"],
                metadata_gaps=record["plug"]["metadata_gaps"], import_status=record["plug"]["status"],
                scientific_review_status="HOLD", server_retains_record=False, report=report,
                diagnostic_error=diagnostic_error, record_base64=base64.b64encode(archive.getvalue()).decode(),
                download_name="Science_Record_" + datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_UTC") + ".zip")


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def send(self, status, body, mime="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/phone-preview":
            self.send(200, '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Science-Sandbox phone layout check</title><style>body{margin:0;background:#0b1218;display:flex;justify-content:center}iframe{width:390px;max-width:100vw;height:calc(100vh - 24px);margin:12px 0;border:0;border-radius:12px}</style><iframe title="Science-Sandbox at phone width" src="/"></iframe></html>', "text/html; charset=utf-8")
        elif self.path == "/health":
            self.send(200, json.dumps(dict(status="ok", app_version=APP_VERSION,
                adapters=["native", "wav", "csv"], physical_hardware_connected=False,
                server_retains_record=False)))
        elif self.path == "/api/equipment-readiness":
            try:
                self.send(200, json.dumps(preparation_status(), allow_nan=False))
            except (ValueError, TypeError, KeyError, AttributeError, OSError):
                self.send(503, '{"error":"Equipment preparation could not be verified","physical_hardware_connected":false}')
        else:
            self.send(404, '{"error":"Not found"}')

    def do_POST(self):
        if self.path != "/api/process":
            self.send(404, '{"error":"Not found"}')
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.send(415, '{"error":"JSON request required"}')
            return
        origin = self.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] != self.headers.get("Host"):
            self.send(403, '{"error":"Use the science page to upload"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_REQUEST:
            self.send(413, '{"error":"Upload exceeds the request limit"}')
            return
        if not WORKER.acquire(blocking=False):
            self.send(503, '{"error":"An analysis is running. Please try again shortly."}')
            return
        try:
            request = json.loads(self.rfile.read(length))
            result = process_record(request)
            self.send(200, json.dumps(result, allow_nan=False))
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as error:
            self.send(400, json.dumps(dict(error=str(error))))
        except Exception:
            self.send(500, '{"error":"Processing did not complete. Your original file is unchanged."}')
        finally:
            WORKER.release()

    def log_message(self, fmt, *args):
        # Do not log recordings, metadata, or request bodies.
        print("science-http", args[0] if args else "request", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), Handler).serve_forever()
