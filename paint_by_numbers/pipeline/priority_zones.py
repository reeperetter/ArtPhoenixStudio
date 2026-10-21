"""Зони пріоритету (розділ 7.8 ТЗ): оператор позначає на фото важливі місця (обличчя, очі, предмет),
а програма зберігає в них більше деталей. Без розпізнавання об'єктів: зони задає людина.

Формат (JSON; координати нормовані 0..1, початок у лівому верхньому куті):

    {"zones": [
      {"name": "обличчя", "shape": "ellipse", "cx": 0.5, "cy": 0.3, "rx": 0.15, "ry": 0.12, "weight": 2.5},
      {"name": "очі", "shape": "rect", "x0": 0.4, "y0": 0.27, "x1": 0.6, "y1": 0.31, "weight": 3},
      {"name": "предмет", "shape": "polygon", "points": [[0.1, 0.1], [0.3, 0.1], [0.2, 0.3]]}
    ]}

`weight` (0..5, типово 2): що більше, то більше деталей. `frame`: "canvas" (типово: координати відносно
полотна, тобто кадру після обрізання) або "photo" (відносно вихідного фото до обрізання).

Вплив зони (див. generate.py): ваги кольорів у K-Means, слабше згладжування, нижчі пороги площі,
пропуск прибирання виступів, слабше спрощення ребер, вища вага в метриках схожості."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

MAX_WEIGHT = 5.0
DEFAULT_WEIGHT = 2.0
UNIT_FULL_WEIGHT = 1.5      # вага, при якій зона вважається «цілком важливою» (unit = 1)


class ZoneError(ValueError):
    """Помилка в описі зон (повідомлення зрозуміле оператору)."""


@dataclass
class Zone:
    name: str
    shape: str
    weight: float
    frame: str
    params: dict


@dataclass
class ZoneInfo:
    name: str
    weight: float
    inside: np.ndarray         # HxW bool: ядро зони (без м'якого краю)
    pixels: int
    polygon_px: np.ndarray     # Nx2 контур у пікселях полотна


@dataclass
class ZoneMaps:
    weight: np.ndarray                         # HxW float32: max(вага * м'який край)
    unit: np.ndarray                           # HxW float32 0..1: важливість для геометрії
    zones: list[ZoneInfo] = field(default_factory=list)


def _num(d: dict, key: str, name: str, lo: float = 0.0, hi: float = 1.0) -> float:
    if key not in d:
        raise ZoneError(f"Зона «{name}»: відсутнє поле «{key}».")
    try:
        v = float(d[key])
    except (TypeError, ValueError):
        raise ZoneError(f"Зона «{name}»: поле «{key}» має бути числом.")
    if not (lo <= v <= hi) or math.isnan(v):
        raise ZoneError(f"Зона «{name}»: поле «{key}» = {v} поза межами {lo}..{hi}.")
    return v


def parse_zones(raw: list[dict] | None) -> list[Zone]:
    zones: list[Zone] = []
    for i, d in enumerate(raw or []):
        if not isinstance(d, dict):
            raise ZoneError(f"Зона №{i + 1} має бути об'єктом JSON.")
        name = str(d.get("name") or f"zone{i + 1}")
        shape = d.get("shape")
        frame = d.get("frame", "canvas")
        if frame not in ("canvas", "photo"):
            raise ZoneError(f"Зона «{name}»: frame має бути «canvas» або «photo».")
        try:
            weight = float(d.get("weight", DEFAULT_WEIGHT))
        except (TypeError, ValueError):
            raise ZoneError(f"Зона «{name}»: weight має бути числом.")
        if not (0 < weight <= MAX_WEIGHT):
            raise ZoneError(f"Зона «{name}»: weight = {weight} поза межами (0, {MAX_WEIGHT:g}].")
        if shape == "rect":
            x0, y0 = _num(d, "x0", name), _num(d, "y0", name)
            x1, y1 = _num(d, "x1", name), _num(d, "y1", name)
            if not (x0 < x1 and y0 < y1):
                raise ZoneError(f"Зона «{name}»: має бути x0 < x1 та y0 < y1.")
            params = dict(x0=x0, y0=y0, x1=x1, y1=y1)
        elif shape == "ellipse":
            params = dict(cx=_num(d, "cx", name), cy=_num(d, "cy", name),
                          rx=_num(d, "rx", name, 1e-4, 1.0), ry=_num(d, "ry", name, 1e-4, 1.0),
                          angle=_num(d, "angle", name, -360, 360) if "angle" in d else 0.0)
        elif shape == "polygon":
            pts = d.get("points")
            if not isinstance(pts, list) or len(pts) < 3:
                raise ZoneError(f"Зона «{name}»: polygon потребує щонайменше 3 точки.")
            clean = []
            for p in pts:
                if not (isinstance(p, (list, tuple)) and len(p) == 2):
                    raise ZoneError(f"Зона «{name}»: кожна точка має вигляд [x, y].")
                clean.append((_num({"x": p[0]}, "x", name), _num({"y": p[1]}, "y", name)))
            params = dict(points=clean)
        else:
            raise ZoneError(f"Зона «{name}»: shape має бути «rect», «ellipse» або «polygon».")
        zones.append(Zone(name, shape, weight, frame, params))
    return zones


def load_zones_file(path: str | Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ZoneError(f"Файл зон не є коректним JSON: {e}")
    return data["zones"] if isinstance(data, dict) and "zones" in data else data


def _polygon_px(z: Zone, W: int, H: int, crop: tuple, src_size: tuple) -> np.ndarray:
    """Контур зони в пікселях робочого полотна."""
    cx0, cy0, cx1, cy1 = crop
    sw, sh = src_size
    if z.frame == "photo":
        s = W / (cx1 - cx0)

        def pt(x, y):
            return ((x * sw - cx0) * s, (y * sh - cy0) * s)

        ax, ay = sw * s, sh * s            # розмір повного фото в пікселях полотна
    else:
        def pt(x, y):
            return (x * W, y * H)

        ax, ay = W, H
    p = z.params
    if z.shape == "rect":
        return np.array([pt(p["x0"], p["y0"]), pt(p["x1"], p["y0"]), pt(p["x1"], p["y1"]), pt(p["x0"], p["y1"])])
    if z.shape == "polygon":
        return np.array([pt(x, y) for x, y in p["points"]])
    cx, cy = pt(p["cx"], p["cy"])
    rx, ry = p["rx"] * ax, p["ry"] * ay
    t = np.linspace(0, 2 * math.pi, 96, endpoint=False)
    a = math.radians(p["angle"])
    ex, ey = rx * np.cos(t), ry * np.sin(t)
    return np.column_stack([cx + ex * math.cos(a) - ey * math.sin(a), cy + ex * math.sin(a) + ey * math.cos(a)])


def rasterize(zones: list[Zone], W: int, H: int, px_per_mm: float, crop: tuple, src_size: tuple,
              feather_mm: float = 2.0) -> ZoneMaps:
    """Ядро зони має повну вагу; назовні вага лінійно спадає до нуля на відстані feather_mm."""
    weight = np.zeros((H, W), np.float32)
    infos: list[ZoneInfo] = []
    fp = max(feather_mm * px_per_mm, 1e-6)
    for z in zones:
        poly = _polygon_px(z, W, H, crop, src_size)
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [np.round(poly * 16).astype(np.int32)], 1, lineType=cv2.LINE_8, shift=4)
        inside = m > 0
        if inside.any():
            dist = cv2.distanceTransform((~inside).astype(np.uint8), cv2.DIST_L2, 3)
            f = np.clip(1.0 - dist / fp, 0.0, 1.0)
        else:
            f = np.zeros((H, W), np.float32)
        f[inside] = 1.0
        weight = np.maximum(weight, f.astype(np.float32) * z.weight)
        infos.append(ZoneInfo(z.name, z.weight, inside, int(inside.sum()), poly))
    unit = np.clip(weight / UNIT_FULL_WEIGHT, 0.0, 1.0).astype(np.float32)
    return ZoneMaps(weight, unit, infos)
