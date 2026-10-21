"""Налаштування генерації. Числа в PRESETS --- стартові гіпотези з ТЗ (розділ 6.4),
а не вимоги: їх потрібно уточнити фізичними тестами."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

ALGORITHM_VERSION = "0.5.0"
PROJECT_FORMAT_VERSION = 1


@dataclass(frozen=True)
class ModePreset:
    n_colors: int
    min_area_mm2: float
    min_width_mm: float
    line_mm: float
    min_digit_mm: float
    denoise_iterations: int


PRESETS: dict[str, ModePreset] = {
    "simple":   ModePreset(16, 25.0, 3.0, 0.25, 2.5, 3),
    "balanced": ModePreset(24, 12.0, 2.0, 0.20, 2.2, 2),
    "detailed": ModePreset(36, 6.0, 1.5, 0.15, 2.0, 1),
}


@dataclass
class Settings:
    mode: str = "balanced"
    n_colors: int | None = None          # None -> з режиму
    width_mm: float = 300.0
    height_mm: float | None = None       # None -> за пропорціями фото
    px_per_mm: float = 3.0               # робоча роздільна здатність
    seed: int = 12345                    # детермінованість (розділ 1.4 ТЗ)
    # проєкт і специфікація фарб (розділ 11 ТЗ)
    order_number: str = "000001"
    project_name: str = ""
    container_ml: float = 3.0                         # номінальний об'єм однієї ємності
    coverage_mm2_per_container: float | None = None   # N: площа, що її покриває 1 ємність (мм²). Не має
                                                      # вбудованого значення: вимірюється фізичними тестами
    safety_factor: float = 1.0                        # K >= 1: шари, втрати, нерівномірність
    coverage_confirmed: bool = False                  # True лише після підтвердження N фізичними тестами
    many_containers_warn: int = 10                    # попередження, якщо одного кольору потрібно більше
    zones: list = field(default_factory=list)         # зони пріоритету (розділ 7.8 ТЗ), формат у priority_zones.py
    zone_feather_mm: float = 2.0                      # ширина м'якого краю зони
    extra: dict = field(default_factory=dict)

    @property
    def preset(self) -> ModePreset:
        return PRESETS[self.mode]

    @property
    def colors(self) -> int:
        return self.n_colors if self.n_colors is not None else self.preset.n_colors

    def to_dict(self) -> dict:
        return asdict(self)
