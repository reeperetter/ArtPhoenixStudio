"""Оркестрація конвеєра (без графічного інтерфейсу): run_pipeline() рахує все в пам'яті,
generate() додатково записує виробничий пакет."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from .export import preview
from .export.package import build_package
from .geometry.labels import NumberSpot, place_numbers_vector
from .geometry.leaders import place_leaders
from .palette.catalog import match_palette
from .geometry.planar import Geometry, build_geometry
from .image_io.loader import load_image
from .palette.specification import compute_spec
from .pipeline.color_quantization import quantize
from .pipeline.preprocess import denoise_zoned, saliency_map, to_lab
from .pipeline.priority_zones import ZoneMaps, parse_zones, rasterize
from .pipeline.regions import RegionMap, connected_regions, merge_small_regions, remove_protrusions
from .quality import warnings as qw
from .settings import ALGORITHM_VERSION, Settings

PREVIEW_SCALE = 2
MAX_NARROW_PASSES = 6
MAX_FINAL_PASSES = 5
KEEP_CONTRAST = 20.0    # вузька ділянка з контрастом (ΔE76) вище цього лишається та потрапляє у звіт


@dataclass
class Result:
    settings: Settings
    rm: RegionMap
    geom: Geometry
    spots: list[NumberSpot]
    spec: dict
    report: dict
    warnings: list[dict]
    width_mm: float
    height_mm: float
    px_per_mm: float
    line_mm: float
    color_img: np.ndarray = field(repr=False, default=None)
    contour_img: np.ndarray = field(repr=False, default=None)
    numbered_img: np.ndarray = field(repr=False, default=None)
    palette_img: np.ndarray = field(repr=False, default=None)
    compare_img: np.ndarray = field(repr=False, default=None)
    zones_img: np.ndarray = field(repr=False, default=None)
    candidates: dict | None = None             # звіт порівняння варіантів (compare.py)
    candidates_img: np.ndarray = field(repr=False, default=None)
    out_dir: Path | None = None
    blocked: bool = False


def run_pipeline(photo: str | Path, settings: Settings) -> Result:
    t: dict = {}
    clock = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        t[name] = round(now - clock, 2)
        clock = now

    p = settings.preset
    ppm = settings.px_per_mm
    img = load_image(str(photo), settings.width_mm, settings.height_mm, ppm)
    lap("load")
    zmaps = build_zone_maps(settings, img)
    zw = zmaps.weight if zmaps else None
    unit = zmaps.unit if zmaps else None
    lab = to_lab(denoise_zoned(img.bgr, p.denoise_iterations, unit))
    sal = saliency_map(img.bgr)
    if unit is not None:
        sal = np.maximum(sal, unit)          # зона пріоритету = максимальна значущість
    lap("preprocess")
    k = settings.colors
    qlabels, _ = quantize(lab, k, settings.seed, weights=None if zw is None else 1.0 + zw)
    lap("quantize")
    L0, col0 = connected_regions(qlabels, k)
    lap("components")
    base_min_px = p.min_area_mm2 * ppm * ppm
    min_digit_px = p.min_digit_mm * ppm
    max_digit_px = min_digit_px * 1.6
    line_px = p.line_mm * ppm
    # найменша площа, у яку ще поміщається номер (2 цифри, якщо кольорів більше 9)
    n_dig = 2 if k > 9 else 1
    r_cap = 0.5 * math.sqrt((0.62 * n_dig) ** 2 + 1.0) * min_digit_px + line_px / 2.0
    floor_px = math.pi * r_cap ** 2
    rm = merge_small_regions(L0, col0, lab, sal, base_min_px, zone=zw, zone_floor_px=floor_px)
    lap("merge")
    # вузькі виступи й перемички вужчі за мінімальну ширину (розділ 8.3 ТЗ), далі повторне об'єднання
    L1 = remove_protrusions(rm.labels, 0.5 * p.min_width_mm * ppm, sal,
                            protect=None if unit is None else unit > 0.3)
    if L1 is not rm.labels:
        cl, cc = connected_regions(rm.color[L1], len(rm.palette_lab))
        rm = merge_small_regions(cl, cc, lab, sal, base_min_px, zone=zw, zone_floor_px=floor_px)
    lap("protrusions")

    # ділянки без місця для номера об'єднуються із сусідами; різко контрастні деталі лишаються
    # й потрапляють у звіт (розділ 9.3 ТЗ). Кілька проходів, бо після об'єднання радіуси змінюються.
    for _ in range(MAX_NARROW_PASSES):
        spots = preview.place_numbers(rm, min_digit_px, max_digit_px, line_px)
        bad = np.array([s.digit_px <= 0 for s in spots])
        if not bad.any():
            break
        before = len(rm.area_px)
        rm = merge_small_regions(rm.labels, rm.color, lab, sal, base_min_px, forced=bad,
                                 keep_contrast=KEEP_CONTRAST, n_before=rm.n_before, zone=zw, zone_floor_px=floor_px)
        if len(rm.area_px) == before:
            break
    lap("numbers")

    # Остаточна гарантія (розділ 9.3 ТЗ): кожна ділянка має номер --- або всередині, або на виносці.
    # Ділянки, що лишилися без номера навіть на виносці, зливаються із сусідом (без винятків за контрастом),
    # після чого геометрія й номери перераховуються.
    merged_for_numbers = 0
    for _ in range(MAX_FINAL_PASSES):
        geom = build_geometry(rm.labels, sal)
        spots = place_numbers_vector(geom.faces, rm.color, min_digit_px, max_digit_px, line_px)
        leaders = place_leaders(spots, geom.chains, rm.labels.shape, min_digit_px, line_px, ppm)
        bad = np.array([s.digit_px <= 0 for s in spots])
        if not bad.any():
            break
        before = len(rm.area_px)
        rm = merge_small_regions(rm.labels, rm.color, lab, sal, base_min_px, forced=bad, keep_contrast=None,
                                 n_before=rm.n_before, zone=zw, zone_floor_px=floor_px)
        merged_for_numbers += before - len(rm.area_px)
        if len(rm.area_px) == before:
            break
    else:                                          # останній прохід змінив розбиття: перерахувати
        geom = build_geometry(rm.labels, sal)
        spots = place_numbers_vector(geom.faces, rm.color, min_digit_px, max_digit_px, line_px)
        leaders = place_leaders(spots, geom.chains, rm.labels.shape, min_digit_px, line_px, ppm)
    lap("geometry+labels")
    cat_match = None
    if settings.catalog:                  # реальні фарби: превʼю й метрики далі рахуються за кольорами фарб
        cat_match = match_palette(rm.palette_lab, settings.catalog)
        rm.palette_lab = np.array([m.paint["lab"] for m in cat_match], np.float32)
    spec = compute_spec(rm, geom, settings, ppm, cat_match)
    lap("spec")

    color_img = preview.render_color(rm)
    contour_img = preview.render_vector(geom.chains, rm.labels.shape, spots, PREVIEW_SCALE, line_px)
    numbered_img = preview.render_vector(geom.chains, rm.labels.shape, spots, PREVIEW_SCALE, line_px, tint=color_img)
    palette_img = preview.render_palette(rm)
    compare_img = preview.compare_panel(img.bgr, color_img, contour_img)
    lap("render")

    # метрики схожості (жодна окрема метрика не є абсолютною, розділ 13.4 ТЗ)
    de = float(np.mean(np.linalg.norm(to_lab(color_img) - to_lab(img.bgr), axis=2)))
    g1 = cv2.cvtColor(img.bgr, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(color_img, cv2.COLOR_BGR2GRAY)
    ssim = float(structural_similarity(g1, g2, data_range=255))
    lap("metrics")

    zone_report = zone_metrics(zmaps, rm, spots, img.bgr, color_img, ppm) if zmaps else None
    areas_mm2 = rm.area_px / (ppm * ppm)
    warns = qw.collect(img.warnings, geom.topology, spots, areas_mm2, settings, spec, k,
                       int(len(rm.palette_lab)), ppm, zone_report)
    catalog_report = None
    if cat_match:
        des = [m.delta_e2000 for m in cat_match]
        catalog_report = {"paints_in_catalog": len(settings.catalog), "mean_delta_e2000": round(float(np.mean(des)), 2),
                          "max_delta_e2000": round(float(np.max(des)), 2),
                          "duplicates": int(sum(m.duplicate for m in cat_match))}
    bm = preview.boundary_mask(rm.labels)
    report = {
        "photo": Path(photo).name,
        "algorithm_version": ALGORITHM_VERSION,
        "work_size_px": list(img.work_size),
        "canvas_mm": [round(img.width_mm, 1), round(img.height_mm, 1)],
        "mode": settings.mode,
        "colors_requested": k,
        "colors_final": int(len(rm.palette_lab)),
        "regions_before_merge": rm.n_before,
        "regions_final": int(len(rm.area_px)),
        "regions_below_min_area": int((areas_mm2 < p.min_area_mm2 * 0.5).sum()),
        "regions_without_number_room": int(sum(1 for s in spots if s.digit_px <= 0)),
        "regions_with_leader": int(leaders["placed"]),
        "regions_merged_for_numbers": int(merged_for_numbers),
        "regions_narrow": int(sum(1 for s in spots if 2 * max(s.radius, 0) / ppm < p.min_width_mm)),
        "topology": geom.topology,
        "priority_zones": zone_report,
        "catalog": catalog_report,
        "spec_totals": spec["totals"],
        "median_region_area_mm2": round(float(np.median(areas_mm2)), 1),
        "boundary_length_m": round(float(bm.sum()) / ppm / 1000.0, 2),
        "mean_delta_e76": round(de, 2),
        "ssim_gray": round(ssim, 3),
        "seed": settings.seed,
        "timings_s": t,
    }
    return Result(settings, rm, geom, spots, spec, report, warns, img.width_mm, img.height_mm, ppm, p.line_mm,
                  color_img, contour_img, numbered_img, palette_img, compare_img,
                  preview.render_zones(img.bgr, zmaps) if zmaps else None)


def build_zone_maps(settings: Settings, img) -> ZoneMaps | None:
    zones = parse_zones(settings.zones)          # ZoneError --- зрозуміле повідомлення оператору
    if not zones:
        return None
    return rasterize(zones, img.work_size[0], img.work_size[1], img.px_per_mm, img.crop, img.src_size,
                     settings.zone_feather_mm)


def zone_metrics(zmaps: ZoneMaps, rm: RegionMap, spots: list[NumberSpot], src_bgr: np.ndarray,
                 color_img: np.ndarray, ppm: float) -> dict:
    """Схожість окремо в зонах пріоритету й поза ними (розділ 13.4 ТЗ). Жодна метрика не абсолютна."""
    dmap = np.linalg.norm(to_lab(color_img) - to_lab(src_bgr), axis=2)
    g1 = cv2.cvtColor(src_bgr, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(color_img, cv2.COLOR_BGR2GRAY)
    _, smap = structural_similarity(g1, g2, data_range=255, full=True)
    union = np.zeros(dmap.shape, bool)
    out = []
    no_room = {s.region for s in spots if s.digit_px <= 0}
    lead = {s.region for s in spots if s.anchor is not None}
    for z in zmaps.zones:
        union |= z.inside
        area_mm2 = z.pixels / (ppm * ppm)
        if z.pixels == 0:
            out.append({"name": z.name, "weight": z.weight, "area_mm2": 0.0, "empty": True})
            continue
        cnt = np.bincount(rm.labels[z.inside].ravel(), minlength=len(rm.area_px))
        inter = np.flatnonzero(cnt)
        out.append({
            "name": z.name, "weight": z.weight, "empty": False, "area_mm2": round(area_mm2, 1),
            "regions": int(len(inter)),
            "regions_per_100mm2": round(100.0 * len(inter) / area_mm2, 2),
            "regions_without_number_room": int(sum(1 for r in inter.tolist() if r in no_room)),
            "regions_with_leader": int(sum(1 for r in inter.tolist() if r in lead)),
            "delta_e76": round(float(dmap[z.inside].mean()), 2),
            "ssim_gray": round(float(smap[z.inside].mean()), 3),
        })
    w = 1.0 + zmaps.weight
    res = {"zones": out}
    res["outside"] = {"delta_e76": round(float(dmap[~union].mean()), 2) if (~union).any() else None,
                      "ssim_gray": round(float(smap[~union].mean()), 3) if (~union).any() else None}
    res["weighted_delta_e76"] = round(float((dmap * w).sum() / w.sum()), 2)
    return res


def preview_zones(photo, settings: Settings):
    """Швидкий перегляд зон на фото без повної генерації (для налаштування зон оператором)."""
    img = load_image(str(photo), settings.width_mm, settings.height_mm, settings.px_per_mm)
    zmaps = build_zone_maps(settings, img)
    if zmaps is None:
        return None
    return preview.render_zones(img.bgr, zmaps)


def generate(photo: str | Path, settings: Settings, out_root: str | Path, force: bool = False) -> Result:
    res = run_pipeline(photo, settings)
    info = build_package(res, out_root, photo, force=force)
    res.out_dir = info["dir"]
    res.blocked = info["blocked"]
    return res
