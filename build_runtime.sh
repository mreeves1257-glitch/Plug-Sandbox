#!/usr/bin/env bash
set -euo pipefail
rm -rf composer/runtime
mkdir -p composer/runtime
cat composer/chunks/chunk_*.b64 | base64 -d > /tmp/ai-composer-runtime.tar.gz
tar -xzf /tmp/ai-composer-runtime.tar.gz -C composer/runtime
# The Composer runtime remains preserved; replace only its shared boundary gateway with the repaired plug.
cp input_gateway.py composer/runtime/input_gateway.py
python -m py_compile composer/runtime/input_gateway.py composer/runtime/engine.py

# Verify the preserved runtime's exact SFZ resource contract before installing assets.
echo '=== SFZ RESOURCE CONTRACT ==='
grep -R -n -E 'SFZ_RENDERER|KARORYFER_BIG_RUSTY_DRUMS|KARORYFER_SHINYGUITAR|KARORYFER_GROWLYBASS|sfizz_render' composer/runtime --include='*.py' --include='*.json' --include='*.txt' 2>/dev/null | head -120 || true

echo '=== TARGET REGISTRY ==='
sed -n '1,170p' composer/runtime/target_registry.json || true
echo '=== SFZ ADAPTER CONTRACT ==='
sed -n '1,180p' composer/runtime/sfz_renderer_adapter.py || true
echo '=== DRUM CHECKPOINT ==='
sed -n '1,140p' composer/runtime/DRUM_EXECUTION_COMPLETION_CHECKPOINT_2026-10-05.txt || true
