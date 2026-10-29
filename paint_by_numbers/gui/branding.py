"""Назва, автор і значки програми (одне місце, щоб не розходилися по вікнах)."""
from __future__ import annotations

import sys
from pathlib import Path

from ..export.pdf import resource_dir

APP_NAME = "ArtPhoenix Studio"
AUTHOR = "reeperetter"


def icon_dir() -> Path:
    return resource_dir() / "assets" / "icons"


def logo_path() -> Path:
    return icon_dir() / "logo_512.png"


def app_icon():
    """QIcon з набору розмірів: логотип (прозорий PNG) + багаторозмірний ICO для дрібних розмірів."""
    from PySide6.QtGui import QIcon
    ic = QIcon(str(icon_dir() / "app.ico"))
    ic.addFile(str(logo_path()))
    return ic


def logo_pixmap(size: int):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    pm = QPixmap(str(logo_path()))
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def set_windows_app_id() -> None:
    """Щоб на панелі завдань Windows була наша іконка, а не іконка Python."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("reeperetter.ArtPhoenixStudio")
        except Exception:
            pass
