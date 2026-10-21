"""Оркестрація конвеєра (без графічного інтерфейсу): run_pipeline() рахує все в пам'яті,
generate() додатково записує виробничий пакет."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from .export import preview
from .export.package import build_package
from .geometry.labels import NumberSpot, place_numbers_vector
from .geometry.planar import Geometry, build_geometry
from .image_io.loader import load_image
from .palette.specification import compute_spec
from .pipeline.color_quantization import quantize
from .pipeline.preprocess import denoise, saliency_map, to_lab
from .pipeline.regions import RegionMap, connected_regions, merge_small_regions, remove_protrusions
from .quality import warnings as qw
from .settings import ALGORITHM_VERSION, Settings

PREVIEW_SCALE = 2
MAX_NARROW_PASSES = 6
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
    lab = to_lab(denoise(img.bgr, p.denoise_iterations))
    sal = saliency_map(img.bgr)
    lap("preprocess")
    k = settings.colors
    qlabels, _ = quantize(lab, k, settings.seed)
    lap("quantize")
    L0, col0 = connected_regions(qlabels, k)
    lap("components")
    base_min_px = p.min_area_mm2 * ppm * ppm
    rm = merge_small_regions(L0, col0, lab, sal, base_min_px)
    lap("merge")
    # вузькі виступи й перемички вужчі за мінімальну ширину (розділ 8.3 ТЗ), далі повторне об'єднання
    L1 = remove_protrusions(rm.labels, 0.5 * p.min_width_mm * ppm, sal)
    if L1 is not rm.labels:
        cl, cc = connected_regions(rm.color[L1], len(rm.palette_lab))
        rm = merge_small_regions(cl, cc, lab, sal, base_min_px)
    lap("protrusions")

    min_digit_px = p.min_digit_mm * ppm
    max_digit_px = min_digit_px * 1.6
    line_px = p.line_mm * ppm
    # ділянки без місця для номера об'єднуються із сусідами; різко контрастні деталі лишаються
    # й потрапляють у звіт (розділ 9.3 ТЗ). Кілька проходів, бо після об'єднання радіуси змінюються.
    for _ in range(MAX_NARROW_PASSES):
        spots = preview.place_numbers(rm, min_digit_px, max_digit_px, line_px)
        bad = np.array([s.digit_px <= 0 for s in spots])
        if not bad.any():
            break
        before = len(rm.area_px)
        rm = merge_small_regions(rm.labels, rm.color, lab, sal, base_min_px, forced=bad,
                                 keep_contrast=KEEP_CONTRAST, n_before=rm.n_before)
        if len(rm.area_px) == before:
            break
    lap("numbers")

    geom = build_geometry(rm.labels, sal)
    lap("geometry")
    spots = place_numbers_vector(geom.faces, rm.color, min_digit_px, max_digit_px, line_px)
    lap("labels")
    spec = compute_spec(rm, geom, settings, ppm)
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

    areas_mm2 = rm.area_px / (ppm * ppm)
    warns = qw.collect(img.warnings, geom.topology, spots, areas_mm2, settings, spec, k,
                       int(len(rm.palette_lab)), ppm)
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
        "regions_narrow": int(sum(1 for s in spots if 2 * max(s.radius, 0) / ppm < p.min_width_mm)),
        "topology": geom.topology,
        "spec_totals": spec["totals"],
        "median_region_area_mm2": round(float(np.median(areas_mm2)), 1),
        "boundary_length_m": round(float(bm.sum()) / ppm / 1000.0, 2),
        "mean_delta_e76": round(de, 2),
        "ssim_gray": round(ssim, 3),
        "seed": settings.seed,
        "timings_s": t,
    }
    return Result(settings, rm, geom, spots, spec, report, warns, img.width_mm, img.height_mm, ppm, p.line_mm,
                  color_img, contour_img, numbered_img, palette_img, compare_img)


def generate(photo: str | Path, settings: Settings, out_root: str | Path, force: bool = False) -> Result:
    res = run_pipeline(photo, settings)
    info = build_package(res, out_root, photo, force=force)
    res.out_dir = info["dir"]
    res.blocked = info["blocked"]
    return res
