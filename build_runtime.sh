#!/usr/bin/env bash
set -euo pipefail

rm -rf composer/runtime
mkdir -p composer/runtime
cat composer/chunks/chunk_*.b64 | base64 -d > /tmp/ai-composer-runtime.tar.gz
tar -xzf /tmp/ai-composer-runtime.tar.gz -C composer/runtime

# Preserve the Composer runtime; replace only its shared boundary gateway.
cp input_gateway.py composer/runtime/input_gateway.py

# Install the real offline SFZ renderer required by the preserved Composer.
TOOLS_DIR="$PWD/.runtime_tools"
mkdir -p "$TOOLS_DIR/bin"
if ! command -v sfizz_render >/dev/null 2>&1; then
  rm -rf "$TOOLS_DIR/sfizz-src" "$TOOLS_DIR/sfizz-build"
  mkdir -p "$TOOLS_DIR/sfizz-src"
  curl -fsSL "https://github.com/sfztools/sfizz/releases/download/1.2.3/sfizz-1.2.3.tar.gz" -o "$TOOLS_DIR/sfizz.tar.gz"
  tar -xzf "$TOOLS_DIR/sfizz.tar.gz" -C "$TOOLS_DIR/sfizz-src" --strip-components=1
  cmake -S "$TOOLS_DIR/sfizz-src" -B "$TOOLS_DIR/sfizz-build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DSFIZZ_JACK=OFF \
    -DSFIZZ_SHARED=OFF \
    -DPLUGIN_LV2=OFF \
    -DPLUGIN_LV2_UI=OFF \
    -DPLUGIN_VST3=OFF \
    -DSFIZZ_RENDER=ON
  cmake --build "$TOOLS_DIR/sfizz-build" --target sfizz_render -j2
  SFIZZ_BIN="$(find "$TOOLS_DIR/sfizz-build" -type f -name sfizz_render -perm -111 | head -1)"
  test -n "$SFIZZ_BIN"
  cp "$SFIZZ_BIN" "$TOOLS_DIR/bin/sfizz_render"
fi
export PATH="$TOOLS_DIR/bin:$PATH"

# Install the exact real-sample libraries declared by target_registry.json.
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

# Normalize Windows-style SFZ path separators for the Linux runtime.
find "$BANK/KARORYFER_SHINYGUITAR" "$BANK/KARORYFER_BIG_RUSTY_DRUMS" -type f -name "*.sfz" -print0 | xargs -0 sed -i 's#\\#/#g'

# Align sample roots with the SFZ programs' relative-path convention.
ln -sfn "$BANK/KARORYFER_SHINYGUITAR/Samples" "$BANK/KARORYFER_SHINYGUITAR/Programs/Samples"
ln -sfn "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Samples" "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/Samples"

# Fail the build rather than deploy another runtime that cannot make audio.
test -x "$TOOLS_DIR/bin/sfizz_render"
test -f "$BANK/KARORYFER_GROWLYBASS_V1_002/growlybass_vicious.sfz"
test -f "$BANK/KARORYFER_SHINYGUITAR/Programs/electric_one.sfz"
test -f "$BANK/KARORYFER_BIG_RUSTY_DRUMS/Programs/01-full.sfz"

python -m py_compile composer/runtime/input_gateway.py composer/runtime/engine.py
echo "REAL AUDIO RUNTIME READY"
