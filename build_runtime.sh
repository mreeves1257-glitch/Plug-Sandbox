#!/usr/bin/env bash
set -euo pipefail
rm -rf composer/runtime
mkdir -p composer/runtime
cat composer/chunks/chunk_*.b64 | base64 -d > /tmp/ai-composer-runtime.tar.gz
tar -xzf /tmp/ai-composer-runtime.tar.gz -C composer/runtime
python -m py_compile composer/runtime/input_gateway.py composer/runtime/engine.py
