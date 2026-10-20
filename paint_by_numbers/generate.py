"""Оркестрація конвеєра етапу 1 (без графічного інтерфейсу)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from .export import preview
from .export.svg import write_svg
from .geometry.labels import place_numbers_vector
from .geometry.planar import build_geometry
from .image_io.loader import load_image
from .pipeline.color_quantization import quantize
from .pipeline.preprocess import denoise, lab_to_bgr_u8, saliency_map, to_lab
from .pipeline.regions import RegionMap, connected_regions, merge_small_regions, remove_protrusions
from .settings import Settings

PREVIEW_SCALE = 2
MAX_NARROW_PASSES = 6
KEEP_CONTRAST = 20.0    # вузька ділянка з контрастом (ΔE76) вище цього лишається та потрапляє у звіт


@dataclass
class Result:
    regions: RegionMap
    report: dict
    out_dir: Path


def generate(photo: str, settings: Settings, out_dir: str | Path) -> Result:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t = {}
    clock = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        t[name] = round(now - clock, 2)
        clock = now

    p = settings.preset
    img = load_image(photo, settings.width_mm, settings.height_mm, settings.px_per_mm)
    lap("load")
    smooth = denoise(img.bgr, p.denoise_iterations)
    lab = to_lab(smooth)
    sal = saliency_map(img.bgr)
    lap("preprocess")
    k = settings.colors
    qlabels, _ = quantize(lab, k, settings.seed)
    lap("quantize")
    L0, col0 = connected_regions(qlabels, k)
    lap("components")
    ppm = settings.px_per_mm
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
    line_px = p.line_mm * ppm
    # вузькі ділянки (номер не поміщається) об'єднуються із сусідами; різко контрастні деталі лишаються
    # і потрапляють у звіт (розділ 9.3 ТЗ). Кілька проходів, бо після об'єднання радіуси змінюються.
    for _ in range(MAX_NARROW_PASSES):
        spots = preview.place_numbers(rm, min_digit_px, max_digit_px=min_digit_px * 1.6, line_px=line_px)
        bad = np.array([s.digit_px <= 0 for s in spots])
        if not bad.any():
            break
        before = len(rm.area_px)
        rm = merge_small_regions(rm.labels, rm.color, lab, sal, base_min_px, forced=bad,
                                 keep_contrast=KEEP_CONTRAST, n_before=rm.n_before)
        if len(rm.area_px) == before:
            break
    lap("numbers")

    # векторна геометрія зі спільними ребрами та номери за полігонами
    geom = build_geometry(rm.labels, sal)
    lap("geometry")
    max_digit_px = min_digit_px * 1.6
    spots = place_numbers_vector(geom.faces, rm.color, min_digit_px, max_digit_px, line_px)
    lap("labels")
    svg_info = write_svg(out / "canvas_outline.svg", geom, spots, ppm, img.width_mm, img.height_mm, p.line_mm)
    lap("svg")

    color_img = preview.render_color(rm)
    contour_img = preview.render_vector(geom.chains, rm.labels.shape, spots, PREVIEW_SCALE, line_px)
    cv2.imwrite(str(out / "color_preview.png"), color_img)
    cv2.imwrite(str(out / "contour_preview.png"), contour_img)
    cv2.imwrite(str(out / "palette.png"), preview.render_palette(rm))
    cv2.imwrite(str(out / "compare.png"), preview.compare_panel(img.bgr, color_img, contour_img))
    lap("render")

    # метрики схожості (жодна окрема метрика не є абсолютною, розділ 13.4 ТЗ)
    lab_res = to_lab(color_img)
    lab_src = to_lab(img.bgr)
    de = float(np.mean(np.linalg.norm(lab_res - lab_src, axis=2)))
    g1 = cv2.cvtColor(img.bgr, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(color_img, cv2.COLOR_BGR2GRAY)
    ssim = float(structural_similarity(g1, g2, data_range=255))
    lap("metrics")

    if not geom.topology["ok"]:
        img.warnings.append("КРИТИЧНО: перевірка топології не пройдена, виробничий пакет не можна формувати.")
    areas_mm2 = rm.area_px / (ppm * ppm)
    bm = preview.boundary_mask(rm.labels)
    report = {
        "photo": Path(photo).name,
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
        "svg": svg_info,
        "median_region_area_mm2": round(float(np.median(areas_mm2)), 1),
        "boundary_length_m": round(float(bm.sum()) / ppm / 1000.0, 2),
        "mean_delta_e76": round(de, 2),
        "ssim_gray": round(ssim, 3),
        "warnings": img.warnings,
        "seed": settings.seed,
        "timings_s": t,
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return Result(rm, report, out)
