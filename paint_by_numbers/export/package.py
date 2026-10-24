"""Виробничий пакет order_XXXXXX/ (розділ 16 ТЗ). Пакет збирається у тимчасовій папці й підміняє
попередній лише після успіху, тому збій не пошкоджує вже збережений проєкт (розділ 19.2 ТЗ)."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from ..quality.warnings import summarize
from ..settings import ALGORITHM_VERSION, PROJECT_FORMAT_VERSION
from .assembly import write_assembly_pdf
from .pdf import write_print_pdf, write_spec_pdf
from .svg import write_svg

DIRS = ["source", "project", "preview", "print", "palette", "production", "quality"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, spec: dict) -> None:
    cols = ["number", "paint_code", "paint_name", "catalog_delta_e2000", "hex", "area_mm2", "area_share_pct", "regions", "containers",
            "container_ml", "total_ml"]
    # ';' і BOM: так файл коректно відкривається в Excel з українськими регіональними налаштуваннями
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols + ["estimate"])
        for p in spec["paints"]:
            w.writerow([p[c] for c in cols] + ["orientational" if spec["calculation"]["provisional"] else "confirmed"])
        t = spec["totals"]
        w.writerow(["TOTAL", "", "", "", "", t["canvas_area_mm2"], 100, "", t["containers"], "", t["total_ml"], ""])


def build_package(res, out_root: str | Path, photo: str | Path, force: bool = False,
                  original_name: str | None = None) -> dict:
    s = res.settings
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    final = out_root / f"order_{s.order_number}"
    tmp = out_root / f".order_{s.order_number}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    for d in DIRS:
        (tmp / d).mkdir(parents=True)

    crit = [w for w in res.warnings if w["severity"] == "critical"]
    blocked = bool(crit) and not force
    exports: list[dict] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def rec(rel: str, kind: str, ok: bool = True, **extra) -> None:
        exports.append({"type": kind, "path": rel, "created": now, "ok": ok, **extra})

    try:
        photo = Path(photo)
        src_rel = f"source/original_photo{photo.suffix.lower()}"
        shutil.copy2(photo, tmp / src_rel)
        rec(src_rel, "source")

        # перегляди
        cv2.imwrite(str(tmp / "preview/color_preview.png"), res.color_img)
        cv2.imwrite(str(tmp / "preview/contour_preview.png"), res.contour_img)
        cv2.imwrite(str(tmp / "preview/numbered_preview.png"), res.numbered_img)
        cv2.imwrite(str(tmp / "palette/palette.png"), res.palette_img)
        cv2.imwrite(str(tmp / "quality/compare.png"), res.compare_img)
        if res.zones_img is not None:
            cv2.imwrite(str(tmp / "quality/zones_preview.png"), res.zones_img)
            rec("quality/zones_preview.png", "png")
        if getattr(res, "candidates", None) is not None:
            cv2.imwrite(str(tmp / "quality/candidates.png"), res.candidates_img)
            rec("quality/candidates.png", "png")
            _write_json(tmp / "quality/candidates.json", res.candidates)
            rec("quality/candidates.json", "json")
        for r in ("preview/color_preview.png", "preview/contour_preview.png", "preview/numbered_preview.png",
                  "palette/palette.png"):
            rec(r, "png")

        if not blocked:
            info = write_svg(tmp / "print/canvas_outline.svg", res.geom, res.spots, res.px_per_mm,
                             res.width_mm, res.height_mm, res.line_mm)
            rec("print/canvas_outline.svg", "svg", width_mm=res.width_mm, height_mm=res.height_mm, **info)
            title = f"{s.project_name or 'Order'} {s.order_number}"
            pinfo = write_print_pdf(tmp / "print/canvas_outline.pdf", res.geom, res.spots, res.px_per_mm,
                                    res.width_mm, res.height_mm, res.line_mm, title)
            rec("print/canvas_outline.pdf", "pdf", **pinfo)
            _write_csv(tmp / "palette/paint_list.csv", res.spec)
            rec("palette/paint_list.csv", "csv")
            meta = {"order_number": s.order_number, "project_name": s.project_name, "width_mm": res.width_mm,
                    "height_mm": res.height_mm, "mode": s.mode, "container_ml": s.container_ml}
            sinfo = write_spec_pdf(tmp / "production/production_specification.pdf", res.spec, meta, res.warnings)
            rec("production/production_specification.pdf", "pdf", **sinfo)
            ainfo = write_assembly_pdf(tmp / "production/assembly_sheet.pdf", res.spec, meta, s.extra.get("kit_items") or None)
            rec("production/assembly_sheet.pdf", "pdf", **ainfo)
            _write_json(tmp / "production/production_specification.json", {
                "order_number": s.order_number, "canvas_mm": [res.width_mm, res.height_mm],
                "line_mm": res.line_mm, "paints": res.spec["paints"], "totals": res.spec["totals"],
                "calculation": res.spec["calculation"]})
            rec("production/production_specification.json", "json")

        report = dict(res.report)
        report["warnings"] = res.warnings
        report["warnings_summary"] = summarize(res.warnings)
        report["blocked"] = blocked
        _write_json(tmp / "quality/quality_report.json", report)
        rec("quality/quality_report.json", "json")

        # проєкт: усе потрібне для повторного відкриття й відтворення контурів (розділ 16.2 ТЗ)
        np.savez_compressed(tmp / "project/regions.npz", labels=res.rm.labels.astype(np.int32),
                            region_color=res.rm.color.astype(np.int32), palette_lab=res.rm.palette_lab,
                            palette_lab_raw=(res.palette_lab_raw if res.palette_lab_raw is not None
                                             else res.rm.palette_lab),
                            n_before=np.int64(res.rm.n_before))
        rec("project/regions.npz", "npz")
        _write_json(tmp / "project/project.json", {
            "project_format_version": PROJECT_FORMAT_VERSION,
            "algorithm_version": ALGORITHM_VERSION,
            "created": now,
            "order_number": s.order_number,
            "project_name": s.project_name,
            "status": "blocked" if blocked else "generated",
            "settings": s.to_dict(),
            "effective": {"merged_for_numbers": res.report.get("regions_merged_for_numbers", 0), "colors": s.colors, "line_mm": res.line_mm, "canvas_mm": [res.width_mm, res.height_mm],
                          "px_per_mm": res.px_per_mm},
            "source": {"file": src_rel, "sha256": _sha256(tmp / src_rel), "original_name": original_name or photo.name},
            "palette": [{"number": p["number"], "paint_code": p["paint_code"], "paint_name": p["paint_name"],
                         "hex": p["hex"], "lab": p["lab"]}
                        for p in res.spec["paints"]],
            "regions_file": "project/regions.npz",
            "spec_calculation": res.spec["calculation"],
            "topology": res.geom.topology,
            "exports": exports,
        })
        # атомарна підміна: попередній пакет видаляється лише тепер
        if final.exists():
            shutil.rmtree(final)
        tmp.rename(final)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"dir": final, "blocked": blocked, "exports": exports}
