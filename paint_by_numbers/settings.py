"""Налаштування генерації. Числа в PRESETS --- стартові гіпотези з ТЗ (розділ 6.4),
а не вимоги: їх потрібно уточнити фізичними тестами."""
from __future__ import annotations

from dataclasses import fields, dataclass, field, asdict

ALGORITHM_VERSION = "0.5.0"
PROJECT_FORMAT_VERSION = 1
MIN_COLORS = 4
MAX_COLORS = 36          # межа кількості кольорів в одній картині (комерційний набір); склад фарб може бути більшим


@dataclass(frozen=True)
class ModePreset:
    n_colors: int
    min_area_mm2: float
    min_width_mm: float
    line_mm: float
    min_digit_mm: float
    denoise_iterations: int
    px_per_mm: float = 3.0       # робоча роздільна здатність: дрібніші деталі потребують більшої


# Сім рівнів від найпростішого до найдокладнішого. Ключі simple/balanced/detailed лишилися (проєкти, налаштування, CLI).
# Це стартові гіпотези (розділ 6.4 ТЗ): мінімальні цифри й ширини треба уточнити фізичними тестами.
PRESETS: dict[str, ModePreset] = {
    "draft":    ModePreset(12, 40.0, 4.0, 0.30, 2.8, 3, 3.0),
    "simple":   ModePreset(16, 25.0, 3.0, 0.25, 2.5, 3, 3.0),
    "medium":   ModePreset(20, 17.0, 2.5, 0.22, 2.35, 2, 3.0),
    "balanced": ModePreset(24, 12.0, 2.0, 0.20, 2.2, 2, 3.0),
    "fine":     ModePreset(28, 8.5, 1.7, 0.175, 2.1, 1, 3.5),
    "detailed": ModePreset(32, 6.0, 1.5, 0.15, 2.0, 1, 4.0),
    "max":      ModePreset(36, 3.5, 1.2, 0.12, 1.8, 1, 5.0),
}
MODE_NAMES_UK = {"draft": "1. Ескіз", "simple": "2. Простий", "medium": "3. Помірний", "balanced": "4. Збалансований",
                 "fine": "5. Докладний", "detailed": "6. Деталізований", "max": "7. Максимальний"}
MODE_NAMES_EN = {"draft": "Draft", "simple": "Simple", "medium": "Medium", "balanced": "Balanced",
                 "fine": "Fine", "detailed": "Detailed", "max": "Maximum"}


@dataclass
class Settings:
    mode: str = "balanced"
    n_colors: int | None = None          # None -> з режиму
    width_mm: float = 300.0
    height_mm: float | None = None       # None -> за пропорціями фото
    px_per_mm: float | None = None       # робоча роздільна здатність; None -> за режимом (3...5 пікселів на мм)
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
    catalog: list = field(default_factory=list)       # каталог фарб (palette/catalog.py); порожній -> без підбору
    catalog_select: bool = True                       # квантування одразу з кольорів каталогу (False: K-Means, потім підбір фарб)
    catalog_max_de2000: float = 10.0                  # гіпотеза: далі за цей поріг колір фарби помітно відрізняється
    detail: float = 1.0                               # множник деталізації 0.5..3: більше = дрібніші ділянки й вужчі деталі
    auto_detail: bool = True                          # автоматична деталізація шкіри/облич (кольоровий поріг, без ШІ)
    auto_detail_strength: float = 1.0                 # вага автозони, як у ручної зони (0..2)
    extra: dict = field(default_factory=dict)

    @property
    def preset(self) -> ModePreset:
        return PRESETS[self.mode]

    @property
    def ppm(self) -> float:
        return float(self.px_per_mm) if self.px_per_mm else self.preset.px_per_mm

    @property
    def colors(self) -> int:
        return self.n_colors if self.n_colors is not None else self.preset.n_colors

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        """Відновлює налаштування з project.json; невідомі ключі ігноруються (сумісність між версіями)."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})
