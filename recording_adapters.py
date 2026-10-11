"""Documented PCM-WAV and uniform CSV file adapters. No hardware drivers."""
from copy import deepcopy
import csv
import io
from pathlib import Path
import wave

from science_plug import VERSION, _finite

MAX_SAMPLES = 2_000_000


def decode_wav(payload):
    with wave.open(io.BytesIO(payload), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        count = source.getnframes()
        rate = source.getframerate()
        if source.getcomptype() != "NONE" or width not in (1, 2, 3, 4):
            raise ValueError("Only uncompressed integer PCM WAV (8/16/24/32 bit) is supported")
        if not channels or not count or rate <= 0:
            raise ValueError("WAV has no usable samples")
        if count * channels > MAX_SAMPLES:
            raise ValueError("WAV exceeds prototype decoding limit; use native archival import")
        frames = source.readframes(count)
    if len(frames) != count * channels * width:
        raise ValueError("WAV is truncated")
    output = [[] for _ in range(channels)]
    for offset in range(0, len(frames), channels * width):
        for channel in range(channels):
            start = offset + channel * width
            value = frames[start] - 128 if width == 1 else int.from_bytes(
                frames[start:start + width], "little", signed=True)
            output[channel].append(float(value))
    return dict(kind="PCM_WAV", sample_rate_hz=rate, frames=count,
                sample_width_bits=width * 8, native_units="PCM_COUNT", samples=output)


def decode_csv(payload, metadata):
    """CSV UTF-8: sample_index,<channel IDs>; consecutive indices start at zero."""
    channels = metadata.get("channels", [])
    ids = [channel.get("id") for channel in channels]
    if not ids or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("CSV requires a unique ID for each declared channel")
    rates = [channel.get("sample_rate_hz") for channel in channels]
    if any(not _finite(rate) or rate <= 0 for rate in rates) or len(set(rates)) != 1:
        raise ValueError("CSV requires one positive declared sample rate for every channel")
    reader = csv.reader(io.StringIO(payload.decode("utf-8-sig")))
    header = next(reader, None)
    if header != ["sample_index", *ids]:
        raise ValueError("CSV header must be sample_index followed by declared channel IDs")
    samples = [[] for _ in ids]
    count = 0
    for row in reader:
        if len(row) != len(ids) + 1:
            raise ValueError("CSV row length mismatch")
        try:
            index = int(row[0])
            values = [float(value) for value in row[1:]]
        except ValueError as error:
            raise ValueError("CSV contains a nonnumeric sample or index") from error
        if index != count:
            raise ValueError("CSV index gap, duplicate, or disorder")
        if any(not _finite(value) for value in values):
            raise ValueError("CSV contains a non-finite sample")
        count += 1
        if count * len(ids) > MAX_SAMPLES:
            raise ValueError("CSV exceeds prototype decoding limit; use native archival import")
        for channel, value in zip(samples, values):
            channel.append(value)
    if not count:
        raise ValueError("CSV has no samples")
    return dict(kind="UNIFORM_CSV", sample_rate_hz=rates[0], frames=count, samples=samples)


class RecordingFileAdapter:
    version = VERSION
    def __init__(self, path, metadata):
        self.path = Path(path)
        self.metadata = deepcopy(metadata)

    def capture(self):
        payload = self.path.read_bytes()
        record = deepcopy(self.metadata)
        if record.get("mode") != "SIMULATED":
            record["mode"] = "FILE_IMPORT"
        record.setdefault("device", {}).update(adapter_id=self.adapter_id, adapter_version=self.version)
        record["native_filename"] = self.path.name
        # Preserve an undecodable native file with an explicit blocker.
        try:
            decoded = self.decode(payload, record)
            record["recording"] = {key: value for key, value in decoded.items() if key != "samples"}
            record["format_gaps"] = self.format_gaps(decoded, record)
        except (ValueError, wave.Error, EOFError, UnicodeError, KeyError, TypeError, AttributeError) as error:
            record["format_gaps"] = [f"format validation failed: {error}"]
        return payload, record

    def format_gaps(self, decoded, record):
        return []


class WavFileAdapter(RecordingFileAdapter):
    adapter_id = "science-pcm-wav-import"

    def decode(self, payload, record):
        return decode_wav(payload)

    def format_gaps(self, decoded, record):
        channels = record.get("channels", [])
        gaps = []
        if len(channels) != len(decoded["samples"]):
            gaps.append("WAV channel count differs from channel mapping")
        for channel in channels:
            if channel.get("sample_rate_hz") != decoded["sample_rate_hz"]:
                gaps.append("WAV header rate differs from declared channel rate")
            if channel.get("native_units") != "PCM_COUNT":
                gaps.append("WAV scaling must declare native units PCM_COUNT")
        return gaps


class CsvFileAdapter(RecordingFileAdapter):
    adapter_id = "science-uniform-csv-import"

    def decode(self, payload, record):
        return decode_csv(payload, record)
