import io
import math
from pathlib import Path
import unittest
import wave

from frequency_analysis import analyze_recording, fft
from recording_adapters import CsvFileAdapter, WavFileAdapter, decode_csv, decode_wav
import test_science_plug
from test_science_plug import TODAY, fixture


def wav_bytes(samples, width=2, channels=1, rate=8192):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        raw = bytearray()
        for value in samples:
            raw.extend(bytes([int(value) + 128]) if width == 1 else int(value).to_bytes(width, "little", signed=True))
        output.writeframes(bytes(raw))
    return buffer.getvalue()


class RecordingTests(unittest.TestCase):
    def setUp(self):
        # Reuse the setup helper without importing a second copy of its tests.
        self.state = test_science_plug.PlugTests()
        self.state.setUp()
        self.plug = self.state.plug

    def tearDown(self):
        self.state.tearDown()

    def import_wav(self, samples, width=2, rate=8192):
        path = Path(self.state.temp.name) / "test.wav"
        path.write_bytes(wav_bytes(samples, width, rate=rate))
        m = fixture()
        m["channels"][0].update(native_units="PCM_COUNT", engineering_units="PCM_COUNT",
                                sample_rate_hz=rate, bandwidth_high_hz=3000)
        adapter = WavFileAdapter(path, m)
        self.plug.register(adapter)
        eid = self.plug.capture(adapter.adapter_id, today=TODAY)
        payload, metadata = self.plug.load(eid)
        return eid, payload, metadata

    def test_pcm_widths_and_signed_values(self):
        for width in (1, 2, 3, 4):
            values = [-100, -1, 0, 1, 100]
            decoded = decode_wav(wav_bytes(values, width))
            self.assertEqual(decoded["samples"][0], values)

    def test_stereo_channels_not_mixed(self):
        decoded = decode_wav(wav_bytes([1, 10, 2, 20], channels=2))
        self.assertEqual(decoded["samples"], [[1, 2], [10, 20]])

    def test_truncated_wav_rejected(self):
        with self.assertRaises(ValueError):
            decode_wav(wav_bytes([0] * 100)[:-10])

    def test_bad_wav_archived_and_blocked(self):
        path = Path(self.state.temp.name) / "bad.wav"
        path.write_bytes(b"not a wav")
        adapter = WavFileAdapter(path, fixture())
        self.plug.register(adapter)
        eid = self.plug.capture(adapter.adapter_id, today=TODAY)
        payload, metadata = self.plug.load(eid)
        self.assertEqual(payload, b"not a wav")
        self.assertEqual(metadata["plug"]["status"], "ARCHIVED / BLOCKED")

    def test_wav_header_rate_mismatch_blocked(self):
        path = Path(self.state.temp.name) / "mismatch.wav"
        path.write_bytes(wav_bytes([0] * 1024))
        adapter = WavFileAdapter(path, fixture())
        self.plug.register(adapter)
        eid = self.plug.capture(adapter.adapter_id, today=TODAY)
        self.assertIn("WAV header rate differs from declared channel rate",
                      self.plug.load(eid)[1]["format_gaps"])

    def test_csv_preserves_samples(self):
        decoded = decode_csv(b"sample_index,pressure\n0,1.5\n1,-2.5\n", fixture())
        self.assertEqual(decoded["samples"], [[1.5, -2.5]])

    def test_csv_index_gap_rejected(self):
        with self.assertRaises(ValueError):
            decode_csv(b"sample_index,pressure\n0,1\n2,2\n", fixture())

    def test_csv_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            decode_csv(b"sample_index,pressure\n0,nan\n", fixture())

    def test_csv_header_mismatch_archived_with_blocker(self):
        path = Path(self.state.temp.name) / "bad.csv"
        path.write_bytes(b"index,wrong\n0,1\n")
        adapter = CsvFileAdapter(path, fixture())
        self.plug.register(adapter)
        eid = self.plug.capture(adapter.adapter_id, today=TODAY)
        self.assertEqual(self.plug.load(eid)[1]["plug"]["status"], "ARCHIVED / BLOCKED")

    def test_file_adapter_preserves_explicit_simulation_label(self):
        path = Path(self.state.temp.name) / "synthetic.wav"
        path.write_bytes(wav_bytes([0] * 1024))
        m = fixture()
        m["mode"] = "SIMULATED"
        adapter = WavFileAdapter(path, m)
        self.plug.register(adapter)
        eid = self.plug.capture(adapter.adapter_id, today=TODAY)
        raw, metadata = self.plug.load(eid)
        self.assertEqual(metadata["mode"], "SIMULATED")
        with self.assertRaises(ValueError):
            analyze_recording(raw, metadata)

    def test_fft_matches_direct_transform(self):
        import cmath
        samples = [1, 2, 3, 4, 5, 6, 7, 8]
        expected = [sum(value * cmath.exp(-2j * math.pi * k * n / 8)
                        for n, value in enumerate(samples)) for k in range(8)]
        for actual, target in zip(fft(samples), expected):
            self.assertLess(abs(actual - target), 1e-10)

    def test_single_tone_frequency_and_amplitude(self):
        samples = [round(10000 * math.sin(2 * math.pi * 512 * n / 8192)) for n in range(2048)]
        _, payload, metadata = self.import_wav(samples)
        report = analyze_recording(payload, metadata)
        peak = report["channels"][0]["frames"][0]["peaks"][0]
        self.assertEqual(peak["frequency_hz"], 512)
        self.assertAlmostEqual(peak["amplitude"], 10000, delta=5)
        self.assertFalse(report["scientific_validity_established"])
        self.assertEqual(report["scientific_review_status"], "HOLD")

    def test_two_tones_both_retained(self):
        samples = [round(8000 * math.sin(2 * math.pi * 512 * n / 8192)
                         + 4000 * math.sin(2 * math.pi * 1024 * n / 8192)) for n in range(2048)]
        _, payload, metadata = self.import_wav(samples)
        report = analyze_recording(payload, metadata)
        peaks = report["channels"][0]["frames"][0]["peaks"]
        self.assertEqual({x["frequency_hz"] for x in peaks[:2]}, {512, 1024})

    def test_chirp_tracks_changing_peak(self):
        rate = 8192
        count = 8192
        samples = [round(10000 * math.sin(2 * math.pi * (200 * (n / rate)
                    + 0.5 * 1800 * (n / rate) ** 2))) for n in range(count)]
        _, payload, metadata = self.import_wav(samples)
        frames = analyze_recording(payload, metadata)["channels"][0]["frames"]
        self.assertLess(frames[0]["peaks"][0]["frequency_hz"], frames[-1]["peaks"][0]["frequency_hz"])
        for frame in frames:
            expected = 200 + 1800 * frame["center_time_seconds"]
            self.assertAlmostEqual(frame["peaks"][0]["frequency_hz"], expected, delta=12)

    def test_silence_has_no_fake_frequency(self):
        _, payload, metadata = self.import_wav([0] * 1024)
        report = analyze_recording(payload, metadata)
        self.assertEqual(report["channels"][0]["frames"][0]["peaks"], [])
        self.assertEqual(report["channels"][0]["rms"], 0)

    def test_short_record_and_bad_fft_settings_rejected(self):
        _, payload, metadata = self.import_wav([0] * 100)
        with self.assertRaises(ValueError):
            analyze_recording(payload, metadata)
        with self.assertRaises(ValueError):
            analyze_recording(payload, metadata, fft_size=100)

    def test_frame_limit_is_explicit(self):
        _, payload, metadata = self.import_wav([0] * 4096)
        report = analyze_recording(payload, metadata, max_frames=1)
        self.assertTrue(report["truncated_to_frame_limit"])
        self.assertEqual(report["analyzed_windows"], 1)

    def test_derivative_survives_restart_and_keeps_raw_unchanged(self):
        eid, payload, metadata = self.import_wav([0] * 1024)
        report = analyze_recording(payload, metadata)
        did = self.plug.save_derivative(eid, report)
        self.plug.close()
        from science_plug import SciencePlug
        self.plug = self.state.plug = SciencePlug(self.state.database)
        parent, stored = self.plug.load_derivative(did)
        self.assertEqual(parent, eid)
        self.assertEqual(stored, report)
        self.assertEqual(self.plug.load(eid)[0], payload)

    def test_derivative_wrong_source_rejected(self):
        eid, payload, metadata = self.import_wav([0] * 1024)
        report = analyze_recording(payload, metadata)
        report["source_payload_sha256"] = "a" * 64
        with self.assertRaises(ValueError):
            self.plug.save_derivative(eid, report)

    def test_derivative_tampering_detected(self):
        eid, payload, metadata = self.import_wav([0] * 1024)
        did = self.plug.save_derivative(eid, analyze_recording(payload, metadata))
        with self.plug.db:
            self.plug.db.execute("UPDATE derivatives SET report='{}' WHERE id=?", (did,))
        with self.assertRaises(ValueError):
            self.plug.load_derivative(did)

    def test_csv_analysis_uses_declared_scale(self):
        path = Path(self.state.temp.name) / "tone.csv"
        path.write_text("sample_index,pressure\n" + "".join(f"{i},{math.sin(2 * math.pi * 1000 * i / 48000)}\n" for i in range(2048)))
        m = fixture()
        m["channels"][0]["scale"] = 2.0
        adapter = CsvFileAdapter(path, m)
        self.plug.register(adapter)
        eid = self.plug.capture(adapter.adapter_id, today=TODAY)
        payload, metadata = self.plug.load(eid)
        report = analyze_recording(payload, metadata)
        self.assertAlmostEqual(report["channels"][0]["ac_rms"], math.sqrt(2), delta=0.02)


if __name__ == "__main__":
    unittest.main(verbosity=2)
