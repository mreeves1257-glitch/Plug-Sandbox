"""Diagnostic FFT reports from recorded samples. Never a scientific conclusion."""
import cmath
import hashlib
import json
import math
from recording_adapters import decode_csv, decode_wav
from science_plug import _finite

METHOD = "Hann-windowed radix-2 FFT; per-frame mean removal"
METHOD_VERSION = "0.2.0"


def fft(values):
    """Iterative radix-2 transform; length is a power of two."""
    size = len(values)
    if size < 2 or size & (size - 1):
        raise ValueError("FFT size must be a power of two >= 2")
    data = list(map(complex, values))
    j = 0
    for i in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            data[i], data[j] = data[j], data[i]
    width = 2
    while width <= size:
        step = cmath.exp(-2j * math.pi / width)
        for start in range(0, size, width):
            factor = 1 + 0j
            for offset in range(width // 2):
                a = data[start + offset]
                b = factor * data[start + offset + width // 2]
                data[start + offset], data[start + offset + width // 2] = a + b, a - b
                factor *= step
        width *= 2
    return data


def analyze_recording(payload, metadata, *, fft_size=1024, hop_size=None, max_frames=256):
    if metadata.get("mode") != "FILE_IMPORT":
        raise ValueError("Diagnostic import analysis requires FILE_IMPORT mode")
    if metadata.get("format_gaps"):
        raise ValueError("Format blockers must be resolved before decoding analysis")
    adapter = metadata.get("device", {}).get("adapter_id")
    if adapter == "science-pcm-wav-import":
        recording = decode_wav(payload)
    elif adapter == "science-uniform-csv-import":
        recording = decode_csv(payload, metadata)
    else:
        raise ValueError("No decoder registered for this adapter")
    if isinstance(fft_size, bool) or not isinstance(fft_size, int) or fft_size < 8 or fft_size > 65536 or fft_size & (fft_size - 1):
        raise ValueError("FFT size must be a power of two between 8 and 65536")
    hop = fft_size // 2 if hop_size is None else hop_size
    if not isinstance(hop, int) or isinstance(hop, bool) or not 1 <= hop <= fft_size:
        raise ValueError("Hop size must be an integer from 1 to FFT size")
    if not isinstance(max_frames, int) or isinstance(max_frames, bool) or not 1 <= max_frames <= 4096:
        raise ValueError("Frame limit must be an integer from 1 to 4096")
    if recording["frames"] < fft_size:
        raise ValueError("Recording is shorter than the requested FFT window")
    channels = metadata.get("channels", [])
    if len(channels) != len(recording["samples"]):
        raise ValueError("Channel mapping does not match recording")
    rate = recording["sample_rate_hz"]
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (fft_size - 1)) for i in range(fft_size)]
    normalization = sum(window)
    available = 1 + (recording["frames"] - fft_size) // hop
    used = min(available, max_frames)
    output = []
    warnings = ["Diagnostic derived output only; scientific review remains required.",
                "Frequency axis uses declared/header sample rate; physical clock accuracy is not established.",
                "Largest spectral peak is not necessarily the fundamental frequency.",
                "FFT bin spacing is not a frequency-accuracy or calibration certificate.",
                "Scale and units are supplied declarations, not independently verified calibration."]
    if metadata.get("plug", {}).get("metadata_gaps"):
        warnings.append("Input metadata has unresolved blockers; report is diagnostic only.")
    for samples, channel in zip(recording["samples"], channels):
        scale, offset = channel.get("scale"), channel.get("offset")
        if not _finite(scale) or not _finite(offset) or not isinstance(channel.get("engineering_units"), str) or not channel["engineering_units"].strip():
            raise ValueError("Explicit scale, offset and engineering units are required for diagnostic amplitudes")
        converted = [x * scale + offset for x in samples]
        if not all(_finite(x) for x in converted):
            raise ValueError("Scaling produced non-finite samples")
        frames = []
        for index in range(used):
            start = index * hop
            segment = converted[start:start + fft_size]
            mean = sum(segment) / fft_size
            transform = fft([(value - mean) * weight for value, weight in zip(segment, window)])
            amplitudes = [abs(value) * (1 if bin_index in (0, fft_size // 2) else 2) / normalization
                          for bin_index, value in enumerate(transform[:fft_size // 2 + 1])]
            peaks = [i for i in range(1, len(amplitudes) - 1)
                     if amplitudes[i] > amplitudes[i - 1] and amplitudes[i] >= amplitudes[i + 1]]
            peaks = sorted(peaks, key=lambda i: amplitudes[i], reverse=True)[:8]
            frames.append(dict(start_sample=start, center_time_seconds=(start + (fft_size - 1) / 2) / rate,
                               spectral_amplitudes=amplitudes,
                               peaks=[dict(frequency_hz=i * rate / fft_size, amplitude=amplitudes[i]) for i in peaks]))
        mean = sum(converted) / len(converted)
        output.append(dict(channel_id=channel.get("id"), declared_units=channel["engineering_units"],
                           mean=mean, rms=math.sqrt(sum(x * x for x in converted) / len(converted)),
                           ac_rms=math.sqrt(sum((x - mean) ** 2 for x in converted) / len(converted)),
                           minimum=min(converted), maximum=max(converted), frames=frames))
    return dict(kind="DIAGNOSTIC DERIVATIVE", method=METHOD, method_version=METHOD_VERSION,
                source_payload_sha256=hashlib.sha256(payload).hexdigest(),
                source_metadata_sha256=hashlib.sha256(json.dumps(metadata, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                scientific_validity_established=False, scientific_review_status="HOLD",
                nominal_sample_rate_hz=rate, fft_size=fft_size, hop_size=hop,
                frequency_bin_spacing_hz=rate / fft_size, window_duration_seconds=fft_size / rate,
                total_sample_frames=recording["frames"], analyzed_windows=used,
                available_windows=available, truncated_to_frame_limit=used < available,
                analyzed_through_sample=(used - 1) * hop + fft_size,
                warnings=warnings, channels=output)
