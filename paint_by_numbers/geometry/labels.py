"""Розміщення номерів у полігонах (розділ 9 ТЗ): полюс недоступності (polylabel), а не центроїд."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.ops import polylabel


@dataclass
class NumberSpot:
    region: int
    number: int        # 1-based номер фарби
    x: float
    y: float
    radius: float      # радіус вписаного кола мінус половина лінії, px (може бути <= 0)
    digit_px: float    # висота цифри, px (0 -> не поміщається)
    # Виноска (розділ 9.3 ТЗ): якщо номер не вміщається, він стоїть у вільному місці (x, y),
    # а лінія веде до точки `anchor` усередині ділянки; `lead_from` --- край рамки номера.
    anchor: tuple[float, float] | None = None
    lead_from: tuple[float, float] | None = None


def digit_height(radius: float, n_digits: int, min_digit_px: float, max_digit_px: float) -> float:
    """Висота цифри, при якій блок тексту (n_digits цифр) вписується в коло радіуса `radius`."""
    if radius <= 0:
        return 0.0
    h = radius / (0.5 * math.sqrt((0.62 * n_digits) ** 2 + 1.0))
    h = min(h, max_digit_px)
    return h if h >= min_digit_px else 0.0


def place_numbers_vector(faces: dict, region_color: np.ndarray, min_digit_px: float,
                         max_digit_px: float, line_px: float) -> list[NumberSpot]:
    spots = []
    for r in sorted(faces):
        poly = faces[r]
        pole = polylabel(poly, 0.25)
        radius = float(shapely.distance(pole, poly.boundary)) - line_px / 2.0
        num = int(region_color[r]) + 1
        spots.append(NumberSpot(r, num, float(pole.x), float(pole.y), radius,
                                digit_height(radius, len(str(num)), min_digit_px, max_digit_px)))
    return spots
