#!/usr/bin/env bash
# Збирання для Linux/macOS через uv (https://docs.astral.sh/uv/). pip не використовується.
# Використання:  packaging/build.sh        Результат: dist/ArtPhoenixStudio/{ArtPhoenixStudio,ArtPhoenixStudio-cli}
# Залежності беруться з pyproject.toml/uv.lock (група «build»), середовище --- .venv-build (системний Python не чіпається).
# Потрібний Python (3.12) uv завантажить сам, якщо його немає. Увесь вивід дублюється в build.log.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
exec > >(tee build.log) 2>&1
trap 'echo; echo "ПОМИЛКА на рядку $LINENO: $BASH_COMMAND" >&2; echo "Надішліть вміст build.log розробнику." >&2' ERR

echo "== Система: $(uname -sr); $(grep -h PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 || true)"
if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'MSG'
Не знайдено uv. Встановіть його одним рядком і відкрийте новий термінал:
    curl -LsSf https://astral.sh/uv/install.sh | sh
(або: pipx install uv / sudo dnf install uv / brew install uv)
MSG
  exit 1
fi
echo "== $(uv --version)"

export UV_PROJECT_ENVIRONMENT=".venv-build"
# 1) середовище з Python 3.12 і залежностями проєкту + група «build» (PyInstaller, PySide6-Essentials)
uv sync --python 3.12 --no-dev --group build
echo "== Python у збірці: $(uv run --no-sync python --version)"
# 2) збирання й самоперевірка
uv run --no-sync pyinstaller packaging/pbn.spec --noconfirm --clean --distpath dist --workpath build
dist/ArtPhoenixStudio/ArtPhoenixStudio-cli --selftest
echo
echo "Готово: dist/ArtPhoenixStudio/ArtPhoenixStudio"
echo "Якщо вікно не відкривається через Qt/xcb:"
echo "  Debian/Ubuntu/Mint: sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1"
echo "  Fedora/Nobara:      sudo dnf install xcb-util-cursor libxkbcommon-x11 mesa-libEGL"
