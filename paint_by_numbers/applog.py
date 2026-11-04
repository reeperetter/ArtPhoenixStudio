"""Технічний журнал помилок (ТЗ 21): ротаційний файл у каталозі даних користувача.
Без персональних даних: домашній каталог і імена файлів у повідомленнях замінюються."""
from __future__ import annotations

import logging
import os
import re
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = "paint_by_numbers"
_MAX_BYTES, _BACKUPS = 512_000, 3


def log_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "ArtPhoenixStudio"


def log_path() -> Path:
    return log_dir() / "errors.log"


_WIN = re.compile(r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*")
_POSIX = re.compile(r"(?<![\w.])/(?:[^/\s'\"]+/)+")


def sanitize(text: str) -> str:
    """Прибирає каталоги з імен файлів (лишається лише імʼя) і домашній каталог."""
    home = str(Path.home())
    if home and home not in ("/", "\\"):
        text = text.replace(home, "~")
    text = _WIN.sub("<dir>\\\\", text)
    return _POSIX.sub(lambda m: m.group(0) if "site-packages" in m.group(0) or "paint_by_numbers" in m.group(0) else "<dir>/", text)


def setup(path: Path | None = None) -> logging.Logger:
    """Підключає файловий обробник (один раз). path --- для тестів."""
    lg = logging.getLogger(LOGGER)
    lg.setLevel(logging.INFO)
    if any(getattr(h, "_pbn", False) for h in lg.handlers):
        return lg
    p = path or log_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(p, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
    except OSError:
        return lg                                           # журнал не повинен ламати програму
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    h._pbn = True                                           # type: ignore[attr-defined]
    lg.addHandler(h)
    return lg


def log_exception(exc: BaseException, where: str = "") -> None:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logging.getLogger(LOGGER).error("%s\n%s", where or "помилка", sanitize(tb))


def install_excepthook() -> None:
    prev = sys.excepthook

    def hook(tp, val, tb):
        if not issubclass(tp, KeyboardInterrupt):
            log_exception(val, "необроблений виняток")
        prev(tp, val, tb)
    sys.excepthook = hook
