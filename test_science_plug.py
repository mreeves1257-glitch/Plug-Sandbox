from copy import deepcopy
from datetime import date
import importlib.util
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from science_plug import FileImportAdapter, SciencePlug, inspect_metadata

TODAY = date(2026, 10, 11)


def fixture():
    return dict(mode="FILE_IMPORT", run_id="TEST-RUN", experiment_id="TEST-EXP",
                component_id="TEST-COMP", source_fingerprint="a" * 64,
                captured_at="2026-10-11T16:00:00-05:00",
                device=dict(manufacturer="TEST ONLY", model="TEST ONLY", asset_id="TEST",
                            adapter_id="science-native-file-import", adapter_version="0.2.1"),
                channels=[dict(id="pressure", quantity="acoustic_pressure", native_units="V",
                               engineering_units="Pa", scale=1.0, offset=0.0, uncertainty=0.01,
                               conditioning="TEST DECLARATION", calibration_reference="TEST CERTIFICATE",
                               calibration_date="2026-01-01", calibration_due="2027-01-01",
                               sample_rate_hz=48000, bandwidth_low_hz=10, bandwidth_high_hz=20000,
                               anti_alias_filter="TEST DECLARATION")],
                timing=dict(clock_source="TEST CLOCK", method="TEST ONLY",
                            measured_alignment_error_seconds=0.0001),
                actual_conditions=["SYNTHETIC TEST FIXTURE; NOT AN EXPERIMENT"])


def load_module(filename, name):
    path = Path(__file__).parent / "reference-source" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class PlugTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.database = Path(self.temp.name) / "evidence.sqlite"
        self.plug = SciencePlug(self.database)

    def tearDown(self):
        self.plug.close()
        self.temp.cleanup()

    def test_well_formed_import_still_requires_review(self):
        eid = self.plug.archive(b"native test bytes", fixture(), today=TODAY)
        payload, metadata = self.plug.load(eid)
        self.assertEqual(payload, b"native test bytes")
        self.assertEqual(metadata["plug"]["status"], "ARCHIVED / SCIENTIFIC REVIEW REQUIRED")
        self.assertFalse(metadata["plug"]["scientific_validity_established"])
        self.assertFalse(metadata["plug"]["execution_authorized"])

    def test_restart_recovers_raw_and_metadata(self):
        eid = self.plug.archive(b"original", fixture(), today=TODAY)
        self.plug.close()
        self.plug = SciencePlug(self.database)
        self.assertEqual(self.plug.load(eid)[0], b"original")

    def test_repeated_imports_have_different_ids(self):
        a = self.plug.archive(b"x", fixture(), today=TODAY)
        b = self.plug.archive(b"x", fixture(), today=TODAY)
        self.assertNotEqual(a, b)

    def test_missing_remains_absent(self):
        eid = self.plug.archive(None, fixture(), today=TODAY)
        raw, m = self.plug.load(eid)
        self.assertIsNone(raw)
        self.assertIn("measurement payload missing; not zero", m["plug"]["metadata_gaps"])

    def test_empty_payload_is_blocked(self):
        eid = self.plug.archive(b"", fixture(), today=TODAY)
        self.assertEqual(self.plug.load(eid)[1]["plug"]["status"], "ARCHIVED / BLOCKED")

    def test_expired_calibration_is_blocked_but_preserved(self):
        m = fixture()
        m["channels"][0]["calibration_due"] = "2026-01-02"
        eid = self.plug.archive(b"evidence", m, today=TODAY)
        raw, result = self.plug.load(eid)
        self.assertEqual(raw, b"evidence")
        self.assertEqual(result["plug"]["status"], "ARCHIVED / BLOCKED")

    def test_numeric_bandwidth_and_uncertainty_requirements(self):
        required = dict(channels=dict(pressure=dict(bandwidth_low_hz=1, bandwidth_high_hz=30000,
                                                     uncertainty=0.001)))
        gaps = inspect_metadata(fixture(), today=TODAY, requirements=required)
        self.assertEqual(len(gaps), 3)

    def test_nyquist_and_missing_channel(self):
        m = fixture()
        m["channels"][0]["sample_rate_hz"] = 40000
        gaps = inspect_metadata(m, today=TODAY, requirements={"channels": {"vibration": {}}})
        self.assertTrue(any("Nyquist" in x for x in gaps))
        self.assertIn("required channel vibration absent", gaps)

    def test_sync_tolerance(self):
        gaps = inspect_metadata(fixture(), today=TODAY,
                                requirements={"max_alignment_error_seconds": 0.00001})
        self.assertIn("timing alignment does not meet experiment", gaps)

    def test_unknown_live_mode_blocked(self):
        m = fixture()
        m["mode"] = "LIVE"
        eid = self.plug.archive(b"x", m, today=TODAY)
        self.assertEqual(self.plug.load(eid)[1]["plug"]["status"], "ARCHIVED / BLOCKED")

    def test_simulation_cannot_enter_science_return(self):
        m = fixture()
        m["mode"] = "SIMULATED"
        eid = self.plug.archive(b"x", m, today=TODAY)
        self.assertIn("NOT SCIENTIFIC EVIDENCE", self.plug.load(eid)[1]["plug"]["status"])
        with self.assertRaises(ValueError):
            self.plug.to_measurement_return(eid, lambda *args: args)

    def test_metadata_and_bytes_are_isolated_from_caller_mutation(self):
        m, raw = fixture(), bytearray(b"original")
        eid = self.plug.archive(raw, m, today=TODAY)
        m["device"]["model"] = "changed"
        raw[:] = b"modified"
        stored, metadata = self.plug.load(eid)
        self.assertEqual(stored, b"original")
        self.assertEqual(metadata["device"]["model"], "TEST ONLY")

    def test_raw_tampering_detected(self):
        eid = self.plug.archive(b"original", fixture(), today=TODAY)
        with self.plug.db:
            self.plug.db.execute("UPDATE evidence SET payload=? WHERE id=?", (b"changed", eid))
        with self.assertRaises(ValueError):
            self.plug.load(eid)

    def test_metadata_tampering_detected(self):
        eid = self.plug.archive(b"original", fixture(), today=TODAY)
        with self.plug.db:
            self.plug.db.execute("UPDATE evidence SET metadata=? WHERE id=?", ("{}", eid))
        with self.assertRaises(ValueError):
            self.plug.load(eid)

    def test_file_adapter_preserves_native_bytes_and_prevents_replacement(self):
        path = Path(self.temp.name) / "native.dat"
        path.write_bytes(b"opaque native test bytes")
        adapter = FileImportAdapter(path, fixture())
        self.plug.register(adapter)
        with self.assertRaises(ValueError):
            self.plug.register(adapter)
        eid = self.plug.capture(adapter.adapter_id, today=TODAY)
        self.assertEqual(self.plug.load(eid)[0], path.read_bytes())

    def test_existing_science_gate_accepts_lineage_but_holds_import(self):
        measurement = load_module("Science-Sandbox-Measurement-Return.py", "plug_test_measurement")
        analysis = load_module("Science-Sandbox-Analysis-Pipeline.py", "plug_test_analysis")
        eid = self.plug.archive(b"native", fixture(), today=TODAY)
        returned = self.plug.to_measurement_return(eid, measurement.MeasurementReturn)
        run = SimpleNamespace(run_id="TEST-RUN", experiment_id="TEST-EXP", component_id="TEST-COMP",
                              source_fingerprint="a" * 64, registration_id="TEST-REG",
                              portal2_record_reference="TEST-P2", planned_conditions=("planned",))
        evidence, result = measurement.EvidenceReturnGate().accept(run, run, returned)
        self.assertEqual(evidence.payload, b"native")
        self.assertEqual(result.measurement_state, "INVALID")
        release = analysis.AnalysisPipeline().release(result)
        self.assertEqual(release.status, "HOLD")
        self.assertFalse(release.released)

    def test_wrong_lineage_rejected_by_existing_gate(self):
        measurement = load_module("Science-Sandbox-Measurement-Return.py", "plug_test_wrong_lineage")
        eid = self.plug.archive(b"native", fixture(), today=TODAY)
        returned = self.plug.to_measurement_return(eid, measurement.MeasurementReturn)
        run = SimpleNamespace(run_id="OTHER-RUN")
        with self.assertRaises(ValueError):
            measurement.EvidenceReturnGate().accept(run, run, returned)

    def test_invalid_metadata_numbers_rejected(self):
        m = fixture()
        m["channels"][0]["uncertainty"] = float("nan")
        with self.assertRaises(ValueError):
            self.plug.archive(b"native", m, today=TODAY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
