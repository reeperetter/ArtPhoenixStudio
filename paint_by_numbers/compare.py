"""Порівняння варіантів налаштувань і автоматичний вибір найкращого (розділ 14 ТЗ).

Алгоритм без ШІ: кожен варіант (режим x кількість кольорів) проходить той самий конвеєр, по ньому
рахуються вимірні показники, а вибір робить явна формула. Усі вагові коефіцієнти нижче --- ГІПОТЕЗИ,
які треба калібрувати на реальних замовленнях; у звіті лежать усі показники, тож оператор може
обрати інший варіант сам. Результат детермінований: однакові вхідні дані дають однаковий вибір.

Оцінка (0..1, більше --- краще):
    fidelity    = 0.5 * (1 - clip(dE / DE_REF, 0, 1)) + 0.5 * SSIM   (dE: зважена за зонами, якщо вони є)
    penalty     = 4 * частка ділянок без номера + 0.5 * частка виносок + 1.0 * частка вузьких
                  + 0.5 * частка дрібних + 0.3 * clip(щільність ділянок / DENSITY_REF, 0, 1)
    workability = 1 - clip(penalty, 0, 1)
    score       = W_FIDELITY * fidelity + W_WORK * workability
Варіанти з критичними попередженнями (блокування виробництва) не обираються."""
from __future__ import annotations

import concurrent.futures as cf
import dataclasses
import multiprocessing as mp
import os
import time
from pathlib import Path

import cv2
import numpy as np

from .export.package import build_package
from .generate import Result, run_pipeline
from .quality.warnings import summarize
from .settings import PRESETS, Settings

DE_REF = 25.0            # ΔE76, при якому внесок точності кольору в оцінку нульовий
DENSITY_REF = 150.0      # ділянок на 100 см², за якого складність вважається граничною
W_FIDELITY, W_WORK = 0.6, 0.4
COLOR_STEP = 8
MARGIN_NOTE = 0.02       # різниця оцінок, нижче якої вибір вважається неоднозначним (гіпотеза)
MODE_ORDER = list(PRESETS)       # «простіший» режим переважає при рівності


def default_variants(base: Settings, modes: list[str] | None = None,
                     colors: list[int] | None = None) -> list[tuple[str, int]]:
    """Список (режим, кількість кольорів). Без явних кольорів: типове значення режиму та +-COLOR_STEP."""
    out: list[tuple[str, int]] = []
    for m in (modes or MODE_ORDER):
        if m not in PRESETS:
            raise ValueError(f"Невідомий режим «{m}».")
        d = PRESETS[m].n_colors
        cs = colors if colors else [d - COLOR_STEP, d, d + COLOR_STEP]
        for c in cs:
            c = int(min(max(c, 4), 64))
            if (m, c) not in out:
                out.append((m, c))
    return out


def metrics_of(res: Result, seconds: float) -> dict:
    r = res.report
    zr = r.get("priority_zones")
    n = max(int(r["regions_final"]), 1)
    area_cm2 = res.width_mm * res.height_mm / 100.0
    sm = summarize(res.warnings)
    return {
        "mode": res.settings.mode, "colors_requested": res.settings.colors, "colors_final": r["colors_final"],
        "regions": r["regions_final"], "regions_no_number": r["regions_without_number_room"],
        "regions_leader": r.get("regions_with_leader", 0), "regions_narrow": r["regions_narrow"],
        "regions_small": r["regions_below_min_area"],
        "regions_per_100cm2": round(n / area_cm2 * 100.0, 2),
        "delta_e76": r["mean_delta_e76"],
        "delta_e76_weighted": zr["weighted_delta_e76"] if zr else r["mean_delta_e76"],
        "ssim": r["ssim_gray"], "containers": r["spec_totals"]["containers"],
        "boundary_length_m": r["boundary_length_m"],
        "critical": sm["critical"], "warnings": sm["warning"], "seconds": round(seconds, 1),
    }


def score_of(m: dict) -> dict:
    n = max(m["regions"], 1)
    fid = 0.5 * (1.0 - min(max(m["delta_e76_weighted"] / DE_REF, 0.0), 1.0)) + 0.5 * min(max(m["ssim"], 0.0), 1.0)
    pen = (4.0 * m["regions_no_number"] / n + 0.5 * m["regions_leader"] / n + 1.0 * m["regions_narrow"] / n
           + 0.5 * m["regions_small"] / n + 0.3 * min(m["regions_per_100cm2"] / DENSITY_REF, 1.0))
    work = 1.0 - min(max(pen, 0.0), 1.0)
    return {"fidelity": round(fid, 4), "workability": round(work, 4),
            "score": round(W_FIDELITY * fid + W_WORK * work, 4)}


def pick_best(rows: list[dict]) -> int | None:
    """Індекс найкращого неблокованого варіанта; при рівності --- менше кольорів, простіший режим."""
    ok = [i for i, r in enumerate(rows) if r["critical"] == 0 and "error" not in r]
    if not ok:
        return None
    return min(ok, key=lambda i: (-rows[i]["score"], rows[i]["colors_requested"], MODE_ORDER.index(rows[i]["mode"])))


def _worker(args) -> dict:
    photo, settings, thumb_h = args
    t = time.perf_counter()
    try:
        res = run_pipeline(photo, settings)
    except Exception as e:                                   # один збійний варіант не зупиняє решту
        return {"mode": settings.mode, "colors_requested": settings.colors, "error": f"{type(e).__name__}: {e}"}
    m = metrics_of(res, time.perf_counter() - t)
    im = res.numbered_img
    s = thumb_h / im.shape[0]
    th = cv2.resize(im, (max(1, int(im.shape[1] * s)), thumb_h), interpolation=cv2.INTER_AREA)
    m["thumb_png"] = cv2.imencode(".png", th)[1].tobytes()
    return m


def run_candidates(photo, base: Settings, variants: list[tuple[str, int]], jobs: int | None = None,
                   thumb_h: int = 520, progress=None) -> list[dict]:
    """Запускає всі варіанти (у кількох процесах) і повертає рядки з показниками та оцінкою."""
    tasks = [(str(photo), dataclasses.replace(base, mode=m, n_colors=c), thumb_h) for m, c in variants]
    jobs = max(1, min(jobs or min(os.cpu_count() or 1, 4), len(tasks)))
    rows: list[dict] = []
    if jobs == 1:
        for i, t in enumerate(tasks):
            rows.append(_worker(t))
            if progress:
                progress(i + 1, len(tasks))
    else:
        with cf.ProcessPoolExecutor(max_workers=jobs, mp_context=mp.get_context("spawn")) as ex:
            for i, r in enumerate(ex.map(_worker, tasks)):       # порядок збігається з порядком варіантів
                rows.append(r)
                if progress:
                    progress(i + 1, len(tasks))
    for r in rows:
        if "error" not in r:
            r.update(score_of(r))
    return rows


def contact_sheet(rows: list[dict], best: int | None) -> np.ndarray:
    """Аркуш мініатюр з оцінками (текст латиницею: шрифт OpenCV без кирилиці)."""
    cells = []
    for i, r in enumerate(rows):
        if "thumb_png" in r:
            th = cv2.imdecode(np.frombuffer(r["thumb_png"], np.uint8), cv2.IMREAD_COLOR)
        else:
            th = np.full((200, 200, 3), 230, np.uint8)
        pad = 4
        th = cv2.copyMakeBorder(th, pad, pad, pad, pad, cv2.BORDER_CONSTANT,
                                value=(60, 170, 60) if i == best else (200, 200, 200))
        lab = np.full((62, th.shape[1], 3), 255, np.uint8)
        if "error" in r:
            lines = [f'{r["mode"]} {r["colors_requested"]}c', "ERROR"]
        else:
            tag = "  BEST" if i == best else ("  BLOCKED" if r["critical"] else "")
            lines = [f'{r["mode"]} {r["colors_requested"]}c{tag}',
                     f'score {r["score"]:.3f}  dE {r["delta_e76_weighted"]:.1f}  SSIM {r["ssim"]:.2f}',
                     f'regions {r["regions"]}  no-num {r["regions_no_number"]}  leaders {r["regions_leader"]}']
        for k, s in enumerate(lines):
            cv2.putText(lab, s, (4, 16 + 18 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)
        cells.append(np.vstack([th, lab]))
    h = max(c.shape[0] for c in cells)
    w = max(c.shape[1] for c in cells)
    cells = [cv2.copyMakeBorder(c, 0, h - c.shape[0], 0, w - c.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))
             for c in cells]
    cols = min(len(cells), 3)
    while len(cells) % cols:
        cells.append(np.full((h, w, 3), 255, np.uint8))
    return np.vstack([np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)])


def compare_report(rows: list[dict], best: int | None) -> dict:
    slim = [{k: v for k, v in r.items() if k != "thumb_png"} for r in rows]
    ok = sorted((r["score"] for r in rows if "score" in r and r["critical"] == 0), reverse=True)
    margin = round(ok[0] - ok[1], 4) if len(ok) > 1 else None
    note = ("Кілька варіантів практично рівноцінні за оцінкою: розгляньте простіший або дешевший "
            "(менше кольорів і ділянок), перегляньте аркуш мініатюр." if margin is not None and margin < MARGIN_NOTE else "")
    return {"margin_to_second": margin, "note": note, "method": "score = 0.6*fidelity + 0.4*workability (гіпотетичні ваги, див. compare.py)",
            "weights": {"fidelity": W_FIDELITY, "workability": W_WORK, "de_ref": DE_REF, "density_ref": DENSITY_REF},
            "selected_index": best, "selected": None if best is None else {"mode": rows[best]["mode"],
                                                                         "colors": rows[best]["colors_requested"]},
            "candidates": slim}


def select_best(photo, base: Settings, variants=None, jobs: int | None = None, progress=None):
    """Повертає (settings найкращого, рядки, індекс, звіт, аркуш). Settings=None, якщо всі варіанти заблоковані."""
    variants = variants or default_variants(base)
    rows = run_candidates(photo, base, variants, jobs, progress=progress)
    best = pick_best(rows)
    sheet = contact_sheet(rows, best)
    chosen = None if best is None else dataclasses.replace(base, mode=rows[best]["mode"],
                                                          n_colors=rows[best]["colors_requested"])
    return chosen, rows, best, compare_report(rows, best), sheet


def generate_best(photo, base: Settings, out_root, variants=None, jobs: int | None = None, force: bool = False,
                  progress=None) -> Result:
    """Порівняти варіанти, перегенерувати найкращий (детерміновано) і зібрати пакет із звітом порівняння."""
    chosen, rows, best, report, sheet = select_best(photo, base, variants, jobs, progress)
    if chosen is None:                      # усі заблоковані: показуємо перший варіант, щоб оператор побачив причини
        ok = [r for r in rows if "error" not in r]
        if not ok:
            raise RuntimeError("Жоден варіант не вдалося побудувати: " + "; ".join(r.get("error", "") for r in rows))
        chosen = dataclasses.replace(base, mode=ok[0]["mode"], n_colors=ok[0]["colors_requested"])
    res = run_pipeline(photo, chosen)
    res.candidates, res.candidates_img = report, sheet
    info = build_package(res, out_root, photo, force=force)
    res.out_dir, res.blocked = info["dir"], info["blocked"]
    return res
