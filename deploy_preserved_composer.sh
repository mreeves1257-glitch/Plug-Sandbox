#!/usr/bin/env bash
set -euo pipefail

# Reconstruct the preserved Composer runtime exactly as checkpointed.
bash build_runtime.sh

# Refuse to deploy an older archive.
test -f composer/runtime/DRUM_EXECUTION_COMPLETION_CHECKPOINT_2026-10-05.txt
test -f composer/runtime/FLAC_RENDERER005_CHECKPOINT_2026-10-05.txt
grep -q "AUDIO_STEMS_READY_MASTER_REQUIRED" composer/runtime/output_handoff.py
grep -q "KARORYFER_GROWLYBASS_V1_002" composer/runtime/target_registry.json

TOOLS_DIR="$PWD/.composer_tools"
mkdir -p "$TOOLS_DIR/bin"

if ! command -v sfizz_render >/dev/null 2>&1 && [ ! -x "$TOOLS_DIR/bin/sfizz_render" ]; then
  rm -rf "$TOOLS_DIR/sfizz-src" "$TOOLS_DIR/sfizz-build"
  mkdir -p "$TOOLS_DIR/sfizz-src"
  curl -fsSL "https://github.com/sfztools/sfizz/releases/download/1.2.3/sfizz-1.2.3.tar.gz" -o "$TOOLS_DIR/sfizz.tar.gz"
  tar -xzf "$TOOLS_DIR/sfizz.tar.gz" -C "$TOOLS_DIR/sfizz-src" --strip-components=1
  cmake -S "$TOOLS_DIR/sfizz-src" -B "$TOOLS_DIR/sfizz-build"     -DCMAKE_BUILD_TYPE=Release     -DSFIZZ_JACK=OFF -DSFIZZ_SHARED=OFF     -DPLUGIN_LV2=OFF -DPLUGIN_LV2_UI=OFF -DPLUGIN_VST3=OFF     -DSFIZZ_RENDER=ON
  cmake --build "$TOOLS_DIR/sfizz-build" --target sfizz_render -j2
  SFIZZ_BIN="$(find "$TOOLS_DIR/sfizz-build" -type f -name sfizz_render -perm -111 | head -1)"
  test -n "$SFIZZ_BIN"
  cp "$SFIZZ_BIN" "$TOOLS_DIR/bin/sfizz_render"
fi

BANK="$PWD/composer/runtime/sound_resources"
mkdir -p "$BANK"

install_library () {
  local rid="$1" repo="$2" branch="$3"
  local dest="$BANK/$rid"
  rm -rf "$dest"
  git clone --depth 1 --branch "$branch" "$repo" "$dest"
  if command -v git-lfs >/dev/null 2>&1; then
    (cd "$dest" && git lfs pull)
  fi
}

install_library "KARORYFER_GROWLYBASS_V1_002" "https://github.com/sfzinstruments/karoryfer.growlybass.git" "master"
install_library "KARORYFER_SHINYGUITAR" "https://github.com/sfzinstruments/karoryfer.shinyguitar.git" "master"
install_library "KARORYFER_BIG_RUSTY_DRUMS" "https://github.com/sfzinstruments/karoryfer.big-rusty-drums.git" "main"

find "$BANK/KARORYFER_SHINYGUITAR" "$BANK/KARORYFER_BIG_RUSTY_DRUMS" -type f -name "*.sfz" -print0 | xargs -0 sed -i 's#\\#/#g'

# Align program-relative sample roots used by the two external libraries.
ln -sfn "$BANK/KARORYFER_SHINYGUITAR/Samples/electric" "$BANK/KARORYFER_SHINYGUITAR/Programs/electric"
ln -sfn "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Samples" "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/mappings/Samples"
ln -sfn "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/mappings" "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/mappings/mappings"

# Composer-facing hi-hat program: real Big Rusty recordings, reduced to one
# close-mic articulation with velocity layers and round robin so normal-mode
# compositions do not load the library's full multi-articulation hi-hat graph.
cat > "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/composer-hihat-lite.sfz" <<'SFZ'
<global> lokey=0 hikey=127 loop_mode=one_shot seq_length=4 ampeg_release=0.20

<group> hivel=15
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl1_rr1.flac
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl1_rr2.flac seq_position=2
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl1_rr3.flac seq_position=3
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl1_rr4.flac seq_position=4

<group> lovel=16 hivel=31
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl2_rr1.flac
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl2_rr2.flac seq_position=2
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl2_rr3.flac seq_position=3
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl2_rr4.flac seq_position=4

<group> lovel=32 hivel=47
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl3_rr1.flac
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl3_rr2.flac seq_position=2
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl3_rr3.flac seq_position=3
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl3_rr4.flac seq_position=4

<group> lovel=48 hivel=63
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl4_rr1.flac
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl4_rr2.flac seq_position=2
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl4_rr3.flac seq_position=3
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl4_rr4.flac seq_position=4

<group> lovel=64 hivel=79
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl5_rr1.flac
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl5_rr2.flac seq_position=2
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl5_rr3.flac seq_position=3
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl5_rr4.flac seq_position=4

<group> lovel=80 hivel=95
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl6_rr1.flac
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl6_rr2.flac seq_position=2
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl6_rr3.flac seq_position=3
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl6_rr4.flac seq_position=4

<group> lovel=96 hivel=111
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl7_rr1.flac
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl7_rr2.flac seq_position=2
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl7_rr3.flac seq_position=3
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl7_rr4.flac seq_position=4

<group> lovel=112 hivel=127
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl8_rr1.flac
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl8_rr2.flac seq_position=2
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl8_rr3.flac seq_position=3
<region> sample=../Samples/hihat_14/tc/cl/ht_tc_vl8_rr4.flac seq_position=4
SFZ

# Deployment-only resource bindings. Composition/theory/performance code is untouched.
python - <<'PY'
import json
from pathlib import Path

path=Path("composer/runtime/target_registry.json")
registry=json.loads(path.read_text())
bindings=registry["targets"]["INTERNAL"].setdefault("instrument_bindings", {})

bindings["electric_guitar:RHYTHM_POWER_CHORDS"]={
    "resource_id":"KARORYFER_SHINYGUITAR","target_gain_db":-5.0,
    "resource_type":"SFZ_SAMPLE_LIBRARY","preferred_mapping":"Programs/electric_one.sfz",
    "library":"Karoryfer Shinyguitar","license":"CC0-1.0",
    "renderer_requirement":"SFZ_COMPATIBLE_SAMPLE_RENDERER",
    "fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"}
bindings["electric_guitar:LEAD_MELODY"]={
    "resource_id":"KARORYFER_SHINYGUITAR","target_gain_db":-6.0,
    "resource_type":"SFZ_SAMPLE_LIBRARY","preferred_mapping":"Programs/electric_one.sfz",
    "library":"Karoryfer Shinyguitar","license":"CC0-1.0",
    "renderer_requirement":"SFZ_COMPATIBLE_SAMPLE_RENDERER",
    "fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"}

programs={
    "kick_drum_rock":(-1.0,"Programs/03-kick.sfz"),
    "snare_drum":(-5.0,"Programs/04-snare.sfz"),
    "hi_hat":(-9.0,"Programs/composer-hihat-lite.sfz"),
    "ride_cymbal":(-8.0,"Programs/07-cymbals.sfz"),
    "crash_cymbal":(-8.0,"Programs/07-cymbals.sfz"),
    "tom_drum":(-4.0,"Programs/05-toms.sfz"),
    "tom_tom":(-4.0,"Programs/05-toms.sfz"),
}
for instrument_id,(gain,mapping) in programs.items():
    bindings[instrument_id]={
        "resource_id":"KARORYFER_BIG_RUSTY_DRUMS","target_gain_db":gain,
        "resource_type":"SFZ_SAMPLE_LIBRARY","preferred_mapping":mapping,
        "library":"Karoryfer Big Rusty Drums","license":"CC0-1.0",
        "renderer_requirement":"SFZ_COMPATIBLE_SAMPLE_RENDERER",
        "fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"}

path.write_text(json.dumps(registry,indent=2)+"\n")
PY

test -f "$BANK/KARORYFER_GROWLYBASS_V1_002/growlybass_vicious.sfz"
test -f "$BANK/KARORYFER_SHINYGUITAR/Programs/electric_one.sfz"
test -f "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/03-kick.sfz"
test -f "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/04-snare.sfz"
test -f "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/composer-hihat-lite.sfz"

python -m pip install -q "numpy>=1.24"
cp composer_support/scene009.py composer/runtime/scene009.py
cp composer_support/master006.py composer/runtime/master006.py
cp composer_support/global_3d_output_gate.py composer/runtime/global_3d_output_gate.py
cp composer_support/spatial_finalizer.py composer/runtime/spatial_finalizer.py
cp composer_support/input_gateway.py composer/runtime/input_gateway.py
cp composer_support/sfz_renderer_adapter.py composer/runtime/sfz_renderer_adapter.py
python -m py_compile composer/runtime/input_gateway.py composer/runtime/engine.py composer/runtime/sfz_renderer_adapter.py composer/runtime/scene009.py composer/runtime/master006.py composer/runtime/global_3d_output_gate.py composer/runtime/spatial_finalizer.py
echo "PRESERVED OCTOBER 5 COMPOSER + 3D OUTPUT HANDOFF READY"
