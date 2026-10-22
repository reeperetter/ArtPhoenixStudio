"""Налаштування застосунку, що зберігаються між запусками (QSettings: реєстр Windows, ~/.config на Linux,
plist на macOS). Пошкоджені або неприпустимі значення мовчки замінюються типовими."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from ..settings import PRESETS

ORG, APP = "paint-by-numbers", "PaintByNumbers"

DEFAULTS = {
    "width_mm": 300.0, "auto_height": True, "height_mm": 400.0, "mode": "balanced",
    "auto_colors": True, "colors": 24, "coverage_mm2": 0.0, "safety_factor": 1.3, "coverage_confirmed": False,
    "catalog_path": "", "last_photo_dir": "", "last_save_dir": "", "last_zones_dir": "", "last_catalog_dir": "",
}
RANGES = {"width_mm": (50.0, 3000.0), "height_mm": (50.0, 3000.0), "colors": (4, 64),
          "coverage_mm2": (0.0, 1e7), "safety_factor": (1.0, 10.0)}


class Prefs:
    def __init__(self, path: str | None = None):
        """path --- файл .ini (для тестів); без нього --- системне сховище."""
        self._s = QSettings(path, QSettings.Format.IniFormat) if path else QSettings(ORG, APP)

    def get(self, key: str):
        default = DEFAULTS[key]
        raw = self._s.value(key, default)
        try:
            if isinstance(default, bool):
                v = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("true", "1", "yes")
            elif isinstance(default, int):
                v = int(float(raw))
            elif isinstance(default, float):
                v = float(raw)
            else:
                v = str(raw)
        except (TypeError, ValueError):
            return default
        if key in RANGES:
            lo, hi = RANGES[key]
            if not (lo <= v <= hi) or v != v:
                return default
        if key == "mode" and v not in PRESETS:
            return default
        return v

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self._s.setValue(key, value)

    def geometry(self) -> QByteArray:
        v = self._s.value("window_geometry")
        return v if isinstance(v, QByteArray) else QByteArray()

    def set_geometry(self, data: QByteArray) -> None:
        self._s.setValue("window_geometry", data)

    def reset(self) -> None:
        self._s.clear()

    def sync(self) -> None:
        self._s.sync()
