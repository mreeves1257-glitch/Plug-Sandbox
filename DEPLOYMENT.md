# Sound, Vibration, Pattern & Consciousness — Online Science-Sandbox

Parent: Science-Sandbox. Role: separate online file-analysis service. Source: science Plug 0.2.1. Scope: native-file, integer PCM WAV and defined uniform CSV imports; diagnostic spectra over time; downloadable evidence records. No composer, panel, portal implementation or protected original changes.

Run `python server.py`; bind address is 0.0.0.0 and port comes from PORT (default 10000). Standard library only; no package installation needed. Health endpoint: /health.

Run checks with `python -m unittest -v test_science_plug test_recordings test_online`.

Uploads are processed in a temporary directory that is removed after generating the response. No server-side evidence catalog or retained upload is advertised. Users must download the full ZIP record to preserve original bytes, metadata, any diagnostic report, SHA-256 checks, and a portable SQLite evidence copy. No recordings or request bodies are committed to GitHub or logged.

The page fits phones and uses normal finger scrolling. Results show frequency spectra and a time-window slider. Frequencies use the declared/header sample rate. Default unsigned/unscaled file values are never represented as calibrated sound pressure. Original acquisition time, machine model, calibration and scientific run lineage remain unknown unless supplied in metadata. Outputs remain on scientific-review HOLD.

Online limits: 10 MB uploads, eight mapped channels, 2,000,000 decoded samples, and at most 128 frequency windows per request (the phone page requests 64). Truncation/analysis extent are explicit. Unsupported or too-short recordings can still be preserved with a diagnostic error. Native files are archived without decoding. CSV requires sample_index followed by channel IDs, consecutive indices starting at zero, finite values, and a supplied uniform sample rate.

This is an online recording-analysis service, not live machine control or a claim that all 24 equipment families have working drivers. Real instrument integration and physical acceptance remain separate work.

## Equipment preparation status

The shared preparation manifest includes 24 instrument-family profiles. Run `python equipment_readiness.py` to inspect them, or request `/api/equipment-readiness` from the online service. The report verifies that the three declared file routes match the implemented adapter classes, validates template structure, and rejects any attempt to claim physical readiness from this preparation manifest. No device discovery, driver installation or activation occurs.

Run all software checks with `python -m unittest test_science_plug test_recordings test_online test_equipment_readiness`. The existing deployment build command runs its original three test modules, including the new readiness HTTP check.

The equipment profiles are connection and metadata placeholders. Raw summary, level and spectrum exports can be preserved natively; only supported PCM WAV and the defined uniformly sampled CSV layout are decoded. Future device integration requires an actual model, official protocol, acquisition host, physical acceptance evidence and the established scientific-review process.
