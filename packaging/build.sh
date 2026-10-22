#!/usr/bin/env bash
# Те саме збирання для Linux/macOS (перевірка специфікації без Windows).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r packaging/requirements-build.txt
pyinstaller packaging/pbn.spec --noconfirm --clean --distpath dist --workpath build
dist/PaintByNumbers/pbn-cli --selftest
