#!/usr/bin/env bash
# Збирання для Linux/macOS у власному віртуальному середовищі (.venv-build): системний Python не чіпається.
# Використання:  packaging/build.sh        Результат: dist/PaintByNumbers/{PaintByNumbers,pbn-cli}
# Увесь вивід дублюється в build.log: якщо щось не вийшло, надішліть останні рядки цього файлу.
#
# Який Python береться: PYTHON=... (якщо задано) -> python3.12 -> python3.13 -> python3 (лише 3.12/3.13).
# Якщо підходящого немає, але встановлено uv (https://docs.astral.sh/uv/), скрипт візьме Python 3.12 через uv.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
exec > >(tee build.log) 2>&1
trap 'echo; echo "ПОМИЛКА на рядку $LINENO: $BASH_COMMAND" >&2; echo "Надішліть вміст build.log розробнику." >&2' ERR

echo "== Система: $(uname -sr); $(grep -h PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 || true)"

ok_python() {   # 0, якщо інтерпретатор $1 існує й має версію 3.12 або 3.13
  command -v "$1" >/dev/null 2>&1 && "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,13)) else 1)' 2>/dev/null
}

PY=""
for c in "${PYTHON:-}" python3.12 python3.13 python3; do
  [ -n "$c" ] && ok_python "$c" && { PY="$c"; break; }
done

VENV=".venv-build"
USE_UV=0
if [ -z "$PY" ]; then
  echo "Python 3.12/3.13 не знайдено (python3 тут: $(python3 --version 2>&1 || echo 'немає'))."
  if command -v uv >/dev/null 2>&1; then
    echo "Беру Python 3.12 через uv…"
    USE_UV=1
  else
    cat >&2 <<'MSG'
Потрібен Python 3.12 або 3.13. Варіанти:
  1) Найпростіше (будь-який дистрибутив, нічого не ламає):
       curl -LsSf https://astral.sh/uv/install.sh | sh      # потім відкрийте новий термінал
       packaging/build.sh
  2) Linux Mint 22 / Ubuntu 24.04 мають Python 3.12:  sudo apt install python3 python3-venv
     Fedora/Nobara: sudo dnf install python3.12   (або python3.13)
MSG
    exit 1
  fi
fi

[ -d "$VENV" ] && [ ! -x "$VENV/bin/python" ] && rm -rf "$VENV"
if [ ! -d "$VENV" ]; then
  if [ "$USE_UV" = 1 ]; then
    uv venv --python 3.12 "$VENV"
  else
    "$PY" -m venv "$VENV" || {
      echo "Не вдалося створити venv. Debian/Ubuntu/Mint: sudo apt install python3-venv  (або встановіть uv, див. вище)" >&2
      rm -rf "$VENV"; exit 1; }
  fi
fi
# shellcheck disable=SC1091
. "$VENV/bin/activate"
echo "== Python у збірці: $(python --version)"
if [ "$USE_UV" = 1 ]; then
  uv pip install -r packaging/requirements-build.txt
else
  python -m pip install --upgrade pip
  python -m pip install -r packaging/requirements-build.txt
fi
pyinstaller packaging/pbn.spec --noconfirm --clean --distpath dist --workpath build
dist/PaintByNumbers/pbn-cli --selftest
echo
echo "Готово: dist/PaintByNumbers/PaintByNumbers"
echo "Якщо вікно не відкривається через Qt/xcb:"
echo "  Debian/Ubuntu/Mint: sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1"
echo "  Fedora/Nobara:      sudo dnf install xcb-util-cursor libxkbcommon-x11 mesa-libEGL"
