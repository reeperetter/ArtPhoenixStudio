from __future__ import annotations

import argparse
import sys

from .compare import default_variants, generate_best
from .generate import generate, preview_zones
from .palette.catalog import CatalogError, load_catalog
from .pipeline.priority_zones import ZoneError, load_zones_file, parse_zones
from .quality.warnings import summarize
from .settings import PRESETS, Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paint-by-numbers",
                                 description="Фото -> виробничий пакет картини за номерами")
    ap.add_argument("photo", nargs="?", help="шлях до фотографії")
    ap.add_argument("--selftest", action="store_true", help="самоперевірка збірки: синтетичне фото, пакет, порівняння")
    ap.add_argument("-o", "--out", default="out", help="коренева папка (всередині створюється order_XXXXXX/)")
    ap.add_argument("--order", default="000001", help="номер замовлення")
    ap.add_argument("--name", default="", help="назва проєкту")
    ap.add_argument("--mode", choices=list(PRESETS), default="balanced")
    ap.add_argument("--colors", type=int, default=None, help="кількість кольорів (4..64)")
    ap.add_argument("--width-mm", type=float, default=300.0)
    ap.add_argument("--height-mm", type=float, default=None)
    ap.add_argument("--px-per-mm", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--coverage-mm2", type=float, default=None,
                    help="норма покриття N однієї ємності 3 мл у мм² (виміряна)")
    ap.add_argument("--safety-factor", type=float, default=1.0, help="коефіцієнт запасу K (>=1)")
    ap.add_argument("--coverage-confirmed", action="store_true",
                    help="норму N підтверджено фізичними тестами (інакше розрахунок орієнтовний)")
    ap.add_argument("--zones", default=None, help="JSON-файл із зонами пріоритету (обличчя, очі тощо)")
    ap.add_argument("--zone-feather-mm", type=float, default=2.0, help="ширина м'якого краю зони, мм")
    ap.add_argument("--catalog", default=None, help="JSON-каталог фарб: кольори буде замінено найближчими фарбами (CIEDE2000)")
    ap.add_argument("--catalog-max-de", type=float, default=10.0, help="поріг ΔE2000 для попередження CAT_FAR")
    ap.add_argument("--compare", action="store_true",
                    help="перебрати варіанти (режим x кількість кольорів), обрати найкращий і зібрати для нього пакет")
    ap.add_argument("--compare-modes", default=None, help="режими для порівняння через кому (типово всі)")
    ap.add_argument("--compare-colors", default=None, help="кількості кольорів через кому (типово типове значення режиму +-8)")
    ap.add_argument("--jobs", type=int, default=None, help="кількість процесів для порівняння (типово до 4)")
    ap.add_argument("--preview-zones", action="store_true",
                    help="лише намалювати зони на фото (zones_preview.png) і вийти")
    ap.add_argument("--force", action="store_true", help="сформувати пакет попри критичні помилки")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.photo:
        ap.error("потрібен шлях до фотографії")
    if a.colors is not None and not 4 <= a.colors <= 64:
        ap.error("--colors має бути в межах 4..64")
    if a.safety_factor < 1:
        ap.error("--safety-factor має бути >= 1")
    zones = []
    if a.zones:
        try:
            zones = load_zones_file(a.zones)
            parse_zones(zones)
        except (ZoneError, OSError) as e:
            print(f"Помилка в зонах пріоритету: {e}", file=sys.stderr)
            return 2
    catalog = []
    if a.catalog:
        try:
            catalog = load_catalog(a.catalog)
        except (CatalogError, OSError) as e:
            print(f"Помилка в каталозі фарб: {e}", file=sys.stderr)
            return 2
    s = Settings(catalog=catalog, catalog_max_de2000=a.catalog_max_de, mode=a.mode, n_colors=a.colors, width_mm=a.width_mm, height_mm=a.height_mm,
                 px_per_mm=a.px_per_mm, seed=a.seed, order_number=a.order, project_name=a.name,
                 coverage_mm2_per_container=a.coverage_mm2, safety_factor=a.safety_factor,
                 coverage_confirmed=a.coverage_confirmed, zones=zones, zone_feather_mm=a.zone_feather_mm)
    if a.preview_zones:
        import os
        import cv2
        img = preview_zones(a.photo, s)
        if img is None:
            print("Зони не задано (--zones).", file=sys.stderr)
            return 2
        os.makedirs(a.out, exist_ok=True)
        path = os.path.join(a.out, "zones_preview.png")
        cv2.imwrite(path, img)
        print(f"Перегляд зон: {path}")
        return 0
    if a.compare:
        try:
            modes = [m.strip() for m in a.compare_modes.split(",")] if a.compare_modes else None
            cols = [int(c) for c in a.compare_colors.split(",")] if a.compare_colors else None
            variants = default_variants(s, modes, cols)
        except ValueError as e:
            ap.error(str(e))
        print(f"Порівняння {len(variants)} варіантів…")
        res = generate_best(a.photo, s, a.out, variants, a.jobs, force=a.force,
                            progress=lambda i, n: print(f"  {i}/{n}", flush=True))
        sel = res.candidates["selected"]
        print(f"Обрано: режим {sel['mode']}, кольорів {sel['colors']}" if sel
              else "Усі варіанти мають критичні помилки; показано перший.")
        if res.candidates["note"]:
            print("  Увага: " + res.candidates["note"])
    else:
        res = generate(a.photo, s, a.out, force=a.force)
    sm = summarize(res.warnings)
    t = res.spec["totals"]
    print(f"Пакет: {res.out_dir}")
    print(f"Ділянок: {res.report['regions_final']}, кольорів: {t['paints']}, ємностей: {t['containers']} "
          f"({t['total_ml']:g} мл){' [орієнтовно]' if res.spec['calculation']['provisional'] else ''}")
    print(f"Попередження: критичних {sm['critical']}, звичайних {sm['warning']}, інформаційних {sm['info']}")
    for w in res.warnings:
        if w["severity"] != "info":
            print(f"  [{w['severity']}] {w['code']}: {w['message']}")
    if res.blocked:
        print("ВИРОБНИЧИЙ ПАКЕТ ЗАБЛОКОВАНО критичними помилками (використайте --force лише після перевірки).")
        return 2
    return 0


def selftest() -> int:
    """Перевіряє, що зібрана програма працює: конвеєр, PDF із кирилицею, SVG, порівняння в кількох процесах."""
    import json
    import tempfile
    from pathlib import Path

    import cv2
    import numpy as np

    from .export.pdf import _register_font
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        rng = np.random.default_rng(1)
        img = np.full((240, 320, 3), (200, 160, 120), np.uint8)
        cv2.circle(img, (160, 120), 70, (40, 60, 200), -1)
        img = np.clip(img.astype(int) + rng.integers(-10, 10, img.shape), 0, 255).astype(np.uint8)
        cv2.imwrite(str(d / "t.png"), img)
        font_ok = _register_font()[2]
        res = generate_best(str(d / "t.png"), Settings(width_mm=100.0, order_number="selftest", zones=[
            {"name": "тест", "shape": "ellipse", "cx": 0.5, "cy": 0.5, "rx": 0.2, "ry": 0.2, "weight": 2}]),
            d / "out", [("simple", 6), ("balanced", 8)], jobs=2)
        pk = d / "out" / "order_selftest"
        need = ["print/canvas_outline.svg", "print/canvas_outline.pdf", "palette/paint_list.csv",
                "production/production_specification.pdf", "quality/candidates.png", "project/project.json"]
        missing = [n for n in need if not (pk / n).exists()]
        topo = json.loads((pk / "quality/quality_report.json").read_text(encoding="utf-8"))["topology"]["ok"]
        ok = not missing and topo and font_ok and not res.blocked
        print(f"SELFTEST {'OK' if ok else 'FAILED'}: шрифт з кирилицею={font_ok}, топологія={topo}, відсутні файли={missing}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
