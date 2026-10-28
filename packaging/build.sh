#!/usr/bin/env bash
# Збирання для Linux/macOS: окреме віртуальне середовище (не чіпає системний Python, працює на Ubuntu/Debian з PEP 668).
# Використання: packaging/build.sh      Результат: dist/PaintByNumbers/{PaintByNumbers,pbn-cli}
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
ver=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$ver" in
  3.12|3.13) ;;
  *) echo "Увага: збірку перевірено на Python 3.12–3.13, у вас $ver. Задайте інший: PYTHON=python3.12 packaging/build.sh" >&2 ;;
esac
if ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then
  echo "Немає модуля venv. Debian/Ubuntu: sudo apt install python3-venv" >&2
  exit 1
fi

VENV=".venv-build"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
# shellcheck disable=SC1091
. "$VENV/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r packaging/requirements-build.txt
pyinstaller packaging/pbn.spec --noconfirm --clean --distpath dist --workpath build
dist/PaintByNumbers/pbn-cli --selftest
echo "Готово: dist/PaintByNumbers/PaintByNumbers"
echo "Якщо вікно не відкривається: sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1"
