#!/usr/bin/env bash
set -euo pipefail
rm -rf composer/runtime
mkdir -p composer/runtime
cp input_gateway.py composer/runtime/input_gateway.py
python -m py_compile composer/runtime/input_gateway.py
echo "PASS-THROUGH PLUG READY"
