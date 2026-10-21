"""Специфікація фарб у ємностях (розділ 11 ТЗ).

Кількість ємностей кольору: n = max(1, ceil(S * K / N)), де S --- сумарна площа кольору (мм²) за
фінальною геометрією, K --- коефіцієнт запасу, N --- норма покриття однієї ємності (мм²).
N не має вбудованого значення: поки її не задано, на кожен колір припадає одна ємність,
а розрахунок позначається як орієнтовний."""
from __future__ import annotations

import math

import numpy as np

from ..export.preview import palette_bgr
from ..geometry.planar import Geometry
from ..pipeline.regions import RegionMap
from ..settings import Settings


def containers_needed(area_mm2: float, coverage_mm2: float | None, safety: float) -> int:
    if not coverage_mm2 or coverage_mm2 <= 0:
        return 1
    return max(1, math.ceil(round(area_mm2 * safety / coverage_mm2, 9)))


def compute_spec(rm: RegionMap, geom: Geometry, settings: Settings, px_per_mm: float, cat_match=None) -> dict:
    k = len(rm.palette_lab)
    area_px = np.zeros(k)
    nreg = np.zeros(k, int)
    for r, poly in geom.faces.items():
        c = int(rm.color[r])
        area_px[c] += poly.area
        nreg[c] += 1
    area_mm2 = area_px / (px_per_mm ** 2)
    total_area = float(area_mm2.sum())
    bgr = palette_bgr(rm)
    N, K = settings.coverage_mm2_per_container, settings.safety_factor
    paints = []
    for i in range(k):
        b, g, r_ = (int(v) for v in bgr[i])
        n = containers_needed(float(area_mm2[i]), N, K)
        m = cat_match[i] if cat_match else None
        paints.append({
            "number": i + 1,
            "paint_code": m.paint["code"] if m else f"P-{i + 1:03d}",
            "paint_name": m.paint["name"] if m else "",
            "catalog_delta_e2000": round(m.delta_e2000, 2) if m else None,
            "catalog_duplicate": bool(m.duplicate) if m else False,
            "hex": f"#{r_:02X}{g:02X}{b:02X}",
            "lab": [round(float(v), 2) for v in rm.palette_lab[i]],
            "area_mm2": round(float(area_mm2[i]), 1),
            "area_share_pct": round(100.0 * float(area_mm2[i]) / total_area, 2) if total_area else 0.0,
            "regions": int(nreg[i]),
            "containers": n,
            "container_ml": settings.container_ml,
            "total_ml": round(n * settings.container_ml, 2),
        })
    provisional = not (settings.coverage_confirmed and N)
    return {
        "paints": paints,
        "totals": {
            "paints": k,
            "containers": int(sum(p["containers"] for p in paints)),
            "total_ml": round(sum(p["total_ml"] for p in paints), 2),
            "canvas_area_mm2": round(total_area, 1),
            "canvas_expected_mm2": round(geom.shape[0] * geom.shape[1] / (px_per_mm ** 2), 1),
        },
        "calculation": {
            "formula": "n = max(1, ceil(S * K / N))",
            "coverage_mm2_per_container_N": N,
            "safety_factor_K": K,
            "coverage_confirmed": bool(settings.coverage_confirmed and N),
            "provisional": provisional,
            "note": ("Орієнтовний розрахунок: норма покриття не задана або не підтверджена фізичними тестами."
                     if provisional else "Норма покриття підтверджена фізичними тестами."),
        },
    }
