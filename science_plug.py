"""Science-Sandbox equipment Plug prototype. No live hardware drivers.

Archives native bytes and metadata before scientific review. An import is never
automatically promoted to a valid scientific measurement or an authorized run.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Protocol
from uuid import uuid4

VERSION = "0.2.1"


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def inspect_metadata(record, *, today=None, requirements=None):
    """Check declarations; does not establish physical calibration or readiness."""
    today = today or date.today()
    requirements = requirements or {}
    gaps = []
    for key in ("run_id", "experiment_id", "component_id"):
        if not _text(record.get(key)):
            gaps.append(f"missing {key}")
    fp = record.get("source_fingerprint")
    if not isinstance(fp, str) or len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
        gaps.append("invalid source fingerprint")
    if record.get("mode") not in {"FILE_IMPORT", "SIMULATED"}:
        gaps.append("unsupported mode; no live hardware driver installed")
    device = record.get("device", {})
    for key in ("manufacturer", "model", "asset_id", "adapter_id", "adapter_version"):
        if not _text(device.get(key)):
            gaps.append(f"missing device.{key}")
    try:
        timestamp = datetime.fromisoformat(record.get("captured_at", "").replace("Z", "+00:00"))
        if timestamp.utcoffset() is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        gaps.append("capture timestamp requires a timezone")
    channels = record.get("channels")
    if not isinstance(channels, list) or not channels:
        gaps.append("no channel mapping")
        channels = []
    seen = set()
    for channel in channels:
        if not isinstance(channel, dict):
            gaps.append("invalid channel record")
            continue
        label = channel.get("id")
        if not _text(label) or label in seen:
            gaps.append("missing or duplicate channel id")
        if _text(label):
            seen.add(label)
        for key in ("quantity", "native_units", "engineering_units", "conditioning", "calibration_reference"):
            if not _text(channel.get(key)):
                gaps.append(f"channel {label}: missing {key}")
        for key in ("scale", "offset", "uncertainty"):
            if not _finite(channel.get(key)):
                gaps.append(f"channel {label}: invalid {key}")
        if _finite(channel.get("uncertainty")) and channel["uncertainty"] < 0:
            gaps.append(f"channel {label}: negative uncertainty")
        low, high = channel.get("bandwidth_low_hz"), channel.get("bandwidth_high_hz")
        valid_band = _finite(low) and _finite(high) and 0 <= low < high
        if not valid_band:
            gaps.append(f"channel {label}: invalid bandwidth")
        sampling = channel.get("sample_rate_hz")
        if not _finite(sampling) or sampling <= 0:
            gaps.append(f"channel {label}: invalid sample rate")
        elif valid_band and sampling <= 2 * high:
            gaps.append(f"channel {label}: declared band reaches or exceeds Nyquist")
        if not _text(channel.get("anti_alias_filter")):
            gaps.append(f"channel {label}: missing anti-alias filter declaration")
        try:
            calibrated = date.fromisoformat(channel.get("calibration_date", ""))
            due = date.fromisoformat(channel.get("calibration_due", ""))
            if calibrated > today or due < today or due < calibrated:
                raise ValueError()
        except (TypeError, ValueError):
            gaps.append(f"channel {label}: calibration dates invalid or expired")
        required = requirements.get("channels", {}).get(label, {})
        if required.get("quantity") is not None and channel.get("quantity") != required["quantity"]:
            gaps.append(f"channel {label}: required quantity mismatch")
        if required.get("engineering_units") is not None and channel.get("engineering_units") != required["engineering_units"]:
            gaps.append(f"channel {label}: required units mismatch")
        for field, comparator in (("bandwidth_low_hz", lambda a, b: a <= b),
                                  ("bandwidth_high_hz", lambda a, b: a >= b),
                                  ("uncertainty", lambda a, b: a <= b)):
            if field in required:
                actual = channel.get(field)
                if not _finite(actual) or not _finite(required[field]) or not comparator(actual, required[field]):
                    gaps.append(f"channel {label}: {field} does not meet experiment")
    for channel_id in requirements.get("channels", {}):
        if channel_id not in seen:
            gaps.append(f"required channel {channel_id} absent")
    timing = record.get("timing", {})
    for key in ("clock_source", "method"):
        if not _text(timing.get(key)):
            gaps.append(f"missing timing.{key}")
    tolerance = requirements.get("max_alignment_error_seconds")
    if tolerance is not None:
        observed = timing.get("measured_alignment_error_seconds")
        if not _finite(tolerance) or tolerance < 0 or not _finite(observed) or observed < 0 or observed > tolerance:
            gaps.append("timing alignment does not meet experiment")
    if not isinstance(record.get("actual_conditions"), list) or not record["actual_conditions"] or not all(_text(x) for x in record["actual_conditions"]):
        gaps.append("actual conditions missing")
    return gaps


class Adapter(Protocol):
    adapter_id: str
    version: str

    def capture(self) -> tuple[bytes | None, dict]: ...


class FileImportAdapter:
    """Native-file import only; no sensor detection or device control."""
    adapter_id = "science-native-file-import"
    version = VERSION

    def __init__(self, path, metadata):
        self.path = Path(path)
        self.metadata = deepcopy(metadata)

    def capture(self):
        record = deepcopy(self.metadata)
        if record.get("mode") != "SIMULATED":
            record["mode"] = "FILE_IMPORT"
        record.setdefault("device", {}).update(adapter_id=self.adapter_id, adapter_version=self.version)
        record["native_filename"] = self.path.name
        return self.path.read_bytes(), record


class SciencePlug:
    """Common adapter registry with transactional, restart-safe evidence storage."""
    def __init__(self, database):
        self.db = sqlite3.connect(database)
        self.db.execute("""CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY, payload BLOB, payload_sha256 TEXT,
            metadata TEXT NOT NULL, metadata_sha256 TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS derivatives (
            id TEXT PRIMARY KEY, import_id TEXT NOT NULL,
            report TEXT NOT NULL, report_sha256 TEXT NOT NULL)""")
        self.adapters = {}

    def close(self):
        self.db.close()

    def register(self, adapter):
        if not _text(adapter.adapter_id) or not _text(adapter.version):
            raise ValueError("Adapter identity and version are required")
        if adapter.adapter_id in self.adapters:
            raise ValueError("Adapter already registered; no silent replacement")
        self.adapters[adapter.adapter_id] = adapter

    def capture(self, adapter_id, *, requirements=None, today=None):
        adapter = self.adapters[adapter_id]
        payload, metadata = adapter.capture()
        metadata = deepcopy(metadata)
        device = metadata.get("device", {})
        if device.get("adapter_id") != adapter.adapter_id or device.get("adapter_version") != adapter.version:
            raise ValueError("Adapter provenance mismatch")
        return self.archive(payload, metadata, requirements=requirements, today=today)

    def archive(self, payload, metadata, *, requirements=None, today=None):
        if payload is not None and not isinstance(payload, (bytes, bytearray)):
            raise ValueError("Native evidence must be bytes or absent")
        record = deepcopy(metadata)
        # Serialize before inspection so malformed non-JSON/non-finite input fails cleanly.
        json.dumps(record, allow_nan=False)
        if not isinstance(record, dict):
            raise ValueError("Metadata must be a JSON object")
        for key in ("device", "timing"):
            if key in record and not isinstance(record[key], dict):
                raise ValueError(f"{key} must be an object")
        gaps = inspect_metadata(record, requirements=requirements, today=today)
        format_gaps = record.get("format_gaps", [])
        if not isinstance(format_gaps, list) or not all(_text(x) for x in format_gaps):
            raise ValueError("format_gaps must be a list of descriptions")
        gaps.extend(format_gaps)
        if payload is None:
            gaps.append("measurement payload missing; not zero")
        elif len(payload) == 0:
            gaps.append("empty measurement payload")
        if record.get("mode") == "SIMULATED":
            status = "SIMULATED / NOT SCIENTIFIC EVIDENCE"
        elif gaps:
            status = "ARCHIVED / BLOCKED"
        else:
            status = "ARCHIVED / SCIENTIFIC REVIEW REQUIRED"
        record["plug"] = dict(version=VERSION, status=status, metadata_gaps=gaps,
                              execution_authorized=False, scientific_validity_established=False,
                              requirements=deepcopy(requirements or {}),
                              metadata_inspection_date=(today or date.today()).isoformat())
        body = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
        raw = bytes(payload) if payload is not None else None
        digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
        identifier = "SCI-IMPORT-" + str(uuid4())
        with self.db:
            self.db.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                            (identifier, raw, digest, body, hashlib.sha256(body.encode()).hexdigest()))
        return identifier

    def load(self, identifier):
        row = self.db.execute("SELECT payload,payload_sha256,metadata,metadata_sha256 FROM evidence WHERE id=?",
                              (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        payload, digest, body, body_digest = row
        if (hashlib.sha256(payload).hexdigest() if payload is not None else None) != digest:
            raise ValueError("Raw evidence integrity failure")
        if hashlib.sha256(body.encode()).hexdigest() != body_digest:
            raise ValueError("Metadata integrity failure")
        return payload, json.loads(body)

    def to_measurement_return(self, identifier, measurement_return_type):
        """Use the existing Science-Sandbox class; keep imported evidence on hold."""
        payload, m = self.load(identifier)
        if m.get("mode") != "FILE_IMPORT":
            raise ValueError("Simulated/unsupported data cannot enter the scientific return path")
        for key in ("run_id", "experiment_id", "component_id", "source_fingerprint"):
            if not _text(m.get(key)):
                raise ValueError("Complete existing run lineage is required")
        if not m.get("actual_conditions"):
            raise ValueError("Actual conditions are required")
        if not isinstance(m["actual_conditions"], list) or not all(_text(x) for x in m["actual_conditions"]):
            raise ValueError("Actual conditions must be a list of descriptions")
        # INVALID is intentional: substantive analysis is held until independent review.
        return measurement_return_type(
            m["run_id"], m["experiment_id"], m["component_id"], m["source_fingerprint"],
            tuple(m["actual_conditions"]), tuple(m.get("deviations", [])),
            "IMPORTED / REVIEW REQUIRED", payload, m, "INVALID")

    def save_derivative(self, identifier, report):
        raw, metadata = self.load(identifier)
        body = json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if (raw is None or report.get("source_payload_sha256") != hashlib.sha256(raw).hexdigest()
                or report.get("source_metadata_sha256") != hashlib.sha256(body.encode()).hexdigest()):
            raise ValueError("Diagnostic derivative source mismatch")
        if (report.get("kind") != "DIAGNOSTIC DERIVATIVE"
                or report.get("scientific_validity_established") is not False
                or report.get("scientific_review_status") != "HOLD"):
            raise ValueError("Diagnostic output cannot claim scientific release")
        body = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
        derivative_id = "SCI-DERIVED-" + str(uuid4())
        with self.db:
            self.db.execute("INSERT INTO derivatives VALUES (?,?,?,?)",
                            (derivative_id, identifier, body, hashlib.sha256(body.encode()).hexdigest()))
        return derivative_id

    def load_derivative(self, derivative_id):
        row = self.db.execute("SELECT import_id,report,report_sha256 FROM derivatives WHERE id=?",
                              (derivative_id,)).fetchone()
        if row is None:
            raise KeyError(derivative_id)
        identifier, body, digest = row
        if hashlib.sha256(body.encode()).hexdigest() != digest:
            raise ValueError("Derived report integrity failure")
        raw, metadata = self.load(identifier)
        report = json.loads(body)
        metadata_body = json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if (raw is None or report["source_payload_sha256"] != hashlib.sha256(raw).hexdigest()
                or report["source_metadata_sha256"] != hashlib.sha256(metadata_body.encode()).hexdigest()):
            raise ValueError("Derived report lineage failure")
        return identifier, report
