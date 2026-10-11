# Sound, Vibration, Pattern & Consciousness — Science Plug prototype

Version: 0.2.1 (installable package). Separate working continuation of the preserved 0.1.0 prototype, within Science-Sandbox. Purpose: provide a common equipment adapter interface, recording decoders, diagnostic frequency analysis, and durable evidence archive without altering the existing portals, composer, control panel, or protected originals. The package filename and checkpoint record contain the exact save time.

## What works in this prototype

- A shared adapter contract: an adapter returns original native bytes plus a common measurement record.
- A native-file import adapter that reads an existing instrument export without changing its contents.
- PCM WAV and defined uniform CSV file adapters; malformed or unsupported files are preserved with an explicit format blocker.
- Diagnostic frequency spectra over time, peak frequencies, and amplitude summaries. Synthetic checks cover tones, multiple simultaneous tones, a sweep, and silence.
- Derived reports stored separately from raw bytes, with source payload/metadata hashes and restart recovery.
- SQLite storage that commits raw bytes and metadata together and reloads them after restart. Import IDs use UUIDs rather than restarting a counter.
- SHA-256 checks on saved bytes and metadata during reload. These detect accidental changes; this is not an authenticated or tamper-proof archive.
- Metadata checks for identity, channel quantities, units, declared conditioning, calibration dates, bandwidth, sample rate, and timing. Numeric experiment requirements can be compared with declarations.
- Clearly separated simulated records. They cannot enter the scientific return bridge.
- A bridge to the existing Science-Sandbox MeasurementReturn format. The existing gate still checks run lineage; imported evidence is marked INVALID / review required and the existing analysis gate holds it.

These checks inspect supplied declarations. They do not physically validate a sensor, its calibration, anti-alias filtering, or time alignment. A positive metadata check means the declarations are complete enough for review, not that a valid experiment has occurred.

## What is not installed

No live USB, serial, Ethernet, manufacturer API, or physiology driver is included. No web server is deployed. No instrument is detected, armed, activated, or remotely controlled. The catalog lists 24 instrument families; it does not represent 24 working device adapters. A specific manufacturer/model and acquisition host are needed to build and verify each live adapter.

The native-file adapter preserves opaque file bytes. The WAV adapter decodes uncompressed integer PCM at 8/16/24/32 bits; compressed audio and unsupported WAV encodings are not decoded. The CSV adapter handles only the documented uniform sampled-channel layout below, not every manufacturer's CSV export. Decoding is limited to 2,000,000 samples across channels in this prototype; larger files can still use native archival import. No frequency slots are required: an appropriate recording can contain tones, sweeps, multiple frequencies, modulation, or complex sound within its measured bandwidth.

## Run the checks

Requires Python 3.10 or newer, using only the standard library.

```bash
python3 -m unittest -v test_science_plug test_recordings
```

The tests use synthetic fixtures and temporary databases. Test calibration declarations and device names are fictional and must never be used as equipment records. `verification.json` contains the actual recorded verification output.

## Import an existing native instrument file

Fill `metadata-template.json` with actual provenance and instrument information. Unknown values may remain null; their absence blocks metadata readiness but the original bytes are still archived. Use existing science run identities, not newly invented substitutes. The input instrument file is read only.

```bash
python3 import_file.py instrument-export.dat metadata-template.json --database science-evidence.sqlite
```

Optional experiment requirements:

```bash
python3 import_file.py instrument-export.dat metadata-template.json --database science-evidence.sqlite --requirements-json requirements-template.json
```

The command reports the import ID, metadata gaps, and review status. It never reports an authorized run or validated scientific measurement. Keep the database and its backups in the project's established evidence storage. This prototype does not itself implement backup scheduling or persist the rest of the Science-Sandbox registries.

## Common record fields

| Group | Required information |
|---|---|
| Lineage | Existing run, experiment, component, source fingerprint |
| Device | Manufacturer, model, asset ID, adapter identity/version |
| Capture | Timezone-aware capture timestamp, actual conditions, deviations |
| Channels | ID, measured quantity, native/engineering units, scale and offset, conditioning |
| Frequency | Validated lower/upper measurement bandwidth, sample rate, anti-alias declaration |
| Calibration | Reference, date, due date, declared uncertainty in engineering units |
| Timing | Clock, synchronization method, measured alignment error when required |
| Evidence | Original bytes, hashes, recorded requirements, metadata inspection gaps |

Sample-rate checks are necessary but not sufficient: bandwidth must come from the full sensor/conditioner/acquisition chain. A counter, spectrum, or level-only export needs an appropriate future record decoder; the current template describes sampled channels.

## WAV and CSV imports

For WAV, each channel must declare the sample rate stored in the file header and native units `PCM_COUNT`. Scale and offset map integer counts into explicitly declared engineering units; an uncalibrated recording must not be labeled pascals or physical sound level by guesswork. A WAV header does not prove microphone calibration or sample-clock accuracy.

```bash
python3 import_file.py recording.wav metadata-template.json --format wav --database science-evidence.sqlite
```

For CSV, declare one positive sample rate for all channels. The UTF-8 header is `sample_index` followed by the exact channel IDs in metadata order. Indices must start at zero and be consecutive, with no missing, duplicated or reordered sample rows. Values must be finite numbers in declared native units.

```csv
sample_index,pressure,vibration
0,0.01,0.002
1,0.02,0.004
```

These numbers illustrate layout only and are not experimental evidence.

```bash
python3 import_file.py recording.csv metadata-template.json --format csv --database science-evidence.sqlite
```

## Diagnostic frequency report

Use the actual import ID returned by the import command:

```bash
python3 analyze_record.py SCI-IMPORT-REPLACE_WITH_ACTUAL_ID --database science-evidence.sqlite --output frequency-report.json
```

The report contains a one-sided Hann-windowed FFT amplitude spectrum for each window, peak-bin frequencies, time positions, means, RMS and AC RMS. It uses per-window mean removal. It does not automatically identify a fundamental, assign harmonic relationships, decode modulation, assess therapeutic effects, or release a scientific conclusion. Frequency axis and engineering amplitudes depend on the supplied rate and calibration scaling.

Default FFT size is 1024, hop is 512 samples, and analysis is limited to the first 256 complete windows. A report explicitly records the available/analyzed windows, analyzed extent and any truncation. `--fft-size` and `--max-frames` allow documented changes. Bin spacing is sample rate divided by FFT size; it is not a statement of physical accuracy. Low-frequency studies may require longer recordings/windows and an appropriate sensor chain.

The command stores the diagnostic report alongside the original import in SQLite and exports a new JSON file. An existing output file is not overwritten. Raw evidence remains separate. Access to raw archival data does not constitute scientific validation; imported records remain held by the existing analysis gate.

## Adapter development boundary

An adapter must identify its own version and device, preserve original samples/exports, record actual settings and status, and report disconnects, overloads and missing measurements honestly. It must never infer physical readiness from a Plug connection alone. Live adapter development should follow the manufacturer documentation and the established Portal Number Two equipment interface.

Adapters implemented here: native file import, PCM WAV import, and defined uniform CSV import. Proposed live interface families: manufacturer USB/Ethernet API; serial instrument; conditioned DAQ; synchronized microphone/accelerometer acquisition; specialized hydrophone, vibrometer, array and acoustic-emission systems. These are development categories, not promises that one generic driver can handle every model.

The two files in `reference-source` are unchanged copies of the existing Measurement Return and Analysis Pipeline modules. They are included solely to verify compatibility; this package does not replace their controlled originals.
