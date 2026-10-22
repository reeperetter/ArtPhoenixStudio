"""Каталог фарб і підбір кольорів за CIEDE2000 (розділ 11 ТЗ). Класична математика, без ШІ.

Формат каталогу (JSON):
    {"name": "Назва каталогу",
     "paints": [{"code": "W-01", "name": "Білий", "hex": "#FFFFFF"},
                {"code": "B-07", "name": "Синій", "lab": [32.3, 79.2, -107.9]}]}
Колір задається `hex` (sRGB, D65) або `lab`. Коди мають бути унікальні.

Підбір: кожному кольору палітри відповідає ОКРЕМА фарба каталогу. Призначення оптимальне за
сумою ΔE2000 (угорський алгоритм); якщо фарб у каталозі менше, ніж кольорів, дублювання
дозволяється, а у звіт іде попередження."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..pipeline.preprocess import to_lab


class CatalogError(ValueError):
    """Помилка в каталозі фарб (повідомлення зрозуміле оператору)."""


@dataclass
class Match:
    paint: dict            # запис каталогу
    delta_e2000: float     # відстань від кольору палітри до фарби
    duplicate: bool = False


def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """ΔE*00 (Sharma, Wu, Dalal 2005) із поширенням розмірностей: (...,3) x (...,3) -> (...)."""
    L1, a1, b1 = (np.asarray(lab1, np.float64)[..., i] for i in range(3))
    L2, a2, b2 = (np.asarray(lab2, np.float64)[..., i] for i in range(3))
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cm7 = ((C1 + C2) / 2.0) ** 7
    G = 0.5 * (1.0 - np.sqrt(Cm7 / (Cm7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0.0, dh)
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh) / 2.0)
    Lbp, Cbp = (L1 + L2) / 2.0, (C1p + C2p) / 2.0
    hsum = h1p + h2p
    hbp = np.where(C1p * C2p == 0, hsum,
                   np.where(np.abs(h1p - h2p) <= 180, hsum / 2.0,
                            np.where(hsum < 360, (hsum + 360) / 2.0, (hsum - 360) / 2.0)))
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dTheta = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dTheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def parse_catalog(data) -> tuple[str, list[dict]]:
    """Перевіряє каталог і повертає (назва, фарби із полями code, name, hex, lab)."""
    if isinstance(data, dict):
        name, raw = str(data.get("name", "catalog")), data.get("paints")
    else:
        name, raw = "catalog", data
    if not isinstance(raw, list) or not raw:
        raise CatalogError("Каталог порожній або не містить списку «paints».")
    out, seen = [], set()
    for i, d in enumerate(raw):
        if not isinstance(d, dict) or not d.get("code"):
            raise CatalogError(f"Фарба №{i + 1}: потрібен об'єкт із полем «code».")
        code = str(d["code"])
        if code in seen:
            raise CatalogError(f"Код фарби «{code}» повторюється.")
        seen.add(code)
        if "hex" in d:
            m = _HEX.match(str(d["hex"]))
            if not m:
                raise CatalogError(f"Фарба «{code}»: hex має вигляд #RRGGBB.")
            h = m.group(1)
            bgr = np.array([[[int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)]]], np.uint8)
            lab = to_lab(bgr)[0, 0]
            hx = "#" + h.upper()
        elif "lab" in d:
            try:
                lab = np.array([float(v) for v in d["lab"]], np.float32)
            except (TypeError, ValueError):
                lab = np.zeros(0)
            if lab.shape != (3,) or not (0 <= lab[0] <= 100) or not np.all(np.isfinite(lab)):
                raise CatalogError(f"Фарба «{code}»: lab має вигляд [L 0..100, a, b].")
            hx = None
        else:
            raise CatalogError(f"Фарба «{code}»: потрібне поле «hex» або «lab».")
        out.append({"code": code, "name": str(d.get("name", "")), "hex": hx,
                    "lab": [round(float(v), 3) for v in lab]})
    return name, out


def load_catalog(path: str | Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CatalogError(f"Файл каталогу не є коректним JSON: {e}")
    return parse_catalog(data)[1]


def match_palette(palette_lab: np.ndarray, catalog: list[dict]) -> list[Match]:
    """Кожному кольору палітри --- окрема фарба каталогу з мінімальною сумарною ΔE2000."""
    if not catalog:
        raise CatalogError("Каталог порожній.")
    cat = np.array([c["lab"] for c in catalog], np.float64)
    cost = ciede2000(np.asarray(palette_lab, np.float64)[:, None, :], cat[None, :, :])
    k, m = cost.shape
    res: list[Match | None] = [None] * k
    rows, cols = linear_sum_assignment(cost)          # детермінований
    for r, c in zip(rows.tolist(), cols.tolist()):
        res[r] = Match(catalog[c], float(cost[r, c]))
    used = {catalog[c]["code"] for c in cols.tolist()}
    for r in range(k):                                # фарб менше, ніж кольорів: дублювання
        if res[r] is None:
            c = int(np.argmin(cost[r]))
            res[r] = Match(catalog[c], float(cost[r, c]), duplicate=True)
    return res  # type: ignore[return-value]
