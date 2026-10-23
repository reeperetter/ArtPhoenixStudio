from __future__ import annotations

import argparse
import sys

from .compare import default_variants, generate_best
from .generate import generate, preview_zones
from .palette.catalog import CatalogError, load_catalog
from .project import ProjectError, open_project
from .pipeline.priority_zones import ZoneError, load_zones_file, parse_zones
from .quality.warnings import summarize
from .settings import PRESETS, Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paint-by-numbers",
                                 description="Фото -> виробничий пакет картини за номерами")
    ap.add_argument("photo", nargs="?", help="шлях до фотографії")
    ap.add_argument("--selftest", action="store_true", help="самоперевірка збірки: синтетичне фото, пакет, порівняння")
    ap.add_argument("-o", "--out", default=None, help="коренева папка (всередині створюється order_XXXXXX/); типово out")
    ap.add_argument("--open-project", metavar="ПАПКА", default=None,
                    help="відкрити збережене замовлення (order_XXXXXX) без перерахунку; з -o зберігає пакет заново")
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
    ap.add_argument("--cost-weight", type=float, default=0.3,
                    help="вага витрат на фарбу в оцінці варіантів (0 --- не враховувати; типово 0.3)")
    ap.add_argument("--jobs", type=int, default=None, help="кількість процесів для порівняння (типово до 4)")
    ap.add_argument("--batch", metavar="ПАПКА_АБО_CSV", default=None,
                    help="пакетна обробка: папка з фото або CSV-маніфест (file;order;name;width_mm;height_mm;mode;colors;zones); "
                         "з --compare для кожного фото обирається найкращий варіант")
    ap.add_argument("--order-numbering", choices=["name", "sequential"], default="name",
                    help="номери замовлень у пакетній обробці: за імʼям файлу або послідовні (типово за імʼям)")
    ap.add_argument("--order-start", type=int, default=1, help="перший номер при послідовній нумерації")
    ap.add_argument("--order-prefix", default="", help="префікс номера замовлення в пакетній обробці")
    ap.add_argument("--skip-existing", action="store_true", help="пакетна обробка: пропускати вже готові замовлення")
    ap.add_argument("--purchase-list", metavar="ПАПКА", default=None,
                    help="зібрати загальний список закупівлі фарб з готових замовлень (order_*) у папці; потрібен каталог фарб")
    ap.add_argument("--bulk-ml", type=float, default=None, help="обʼєм великої тари фарби, мл (для переліку закупівлі)")
    ap.add_argument("--fill-loss", type=float, default=0.0, help="втрати при розливі, %% (для переліку закупівлі)")
    ap.add_argument("--preview-zones", action="store_true",
                    help="лише намалювати зони на фото (zones_preview.png) і вийти")
    ap.add_argument("--force", action="store_true", help="сформувати пакет попри критичні помилки")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.open_project:
        return reopen(a.open_project, a.out, a.force)
    if a.purchase_list:
        return purchase_cli(a.purchase_list, a.bulk_ml, a.fill_loss)
    if not a.photo and not a.batch:
        ap.error("потрібен шлях до фотографії (або --batch)")
    a.out = a.out or "out"
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
    if a.batch:
        return run_batch_cli(a, s)
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
                            progress=lambda i, n: print(f"  {i}/{n}", flush=True), cost_weight=a.cost_weight)
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


def run_batch_cli(a, base: Settings) -> int:
    from .batch import build_items, exit_code, run_batch, write_report
    try:
        items = build_items(a.batch, base, a.order_numbering, a.order_start, a.order_prefix)
    except ValueError as e:
        print(f"Помилка пакетної обробки: {e}", file=sys.stderr)
        return 2
    if not items:
        print("У вказаному місці немає фото.", file=sys.stderr)
        return 2
    bad = sum(1 for i in items if i.settings is None)
    print(f"Фото: {len(items)}" + (f" (з помилками: {bad})" if bad else "") + (", з вибором найкращого варіанта" if a.compare else ""))
    marks = {"ok": "OK", "blocked": "ЗАБЛОКОВАНО", "error": "ПОМИЛКА", "skipped": "пропущено", "cancelled": "перервано"}

    def progress(done, total, row):
        extra = f" --- {row['message']}" if row["message"] else ""
        print(f"[{done}/{total}] {row['file']} -> order_{row['order']}: {marks.get(row['status'], row['status'])}{extra}", flush=True)

    rows = run_batch(items, a.out, a.jobs, a.compare, a.skip_existing, a.force, progress)
    rep = write_report(rows, a.out, base)
    from collections import Counter
    c = Counter(r["status"] for r in rows)
    print("Підсумок: " + ", ".join(f"{marks.get(k, k)} {v}" for k, v in c.items()) + f". Звіт: {rep}")
    if base.catalog and any(r["status"] == "ok" for r in rows):
        purchase_cli(a.out, a.bulk_ml, a.fill_loss)
    elif not base.catalog:
        print("Загальний список закупівлі не створено: потрібен каталог фарб (--catalog).")
    return exit_code(rows)


def purchase_cli(root: str, bulk_ml: float | None, fill_loss: float) -> int:
    from .purchase import PurchaseError, build_purchase_list, write_purchase_files
    try:
        data = build_purchase_list(root, bulk_ml, fill_loss)
        files = write_purchase_files(data, root)
    except (PurchaseError, OSError) as e:
        print(f"Список закупівлі: {e}", file=sys.stderr)
        return 2
    t = data["totals"]
    print(f"Список закупівлі: замовлень {t['orders']}, фарб {t['paints']}, ємностей {t['containers']} ({t['total_ml']:g} мл)"
          f"{' [орієнтовно]' if data['provisional'] else ''}: {files['xlsx']}")
    for e in data["excluded_orders"]:
        print(f"  не включено {e['order']}: {e['reason']}")
    if data["code_conflicts"]:
        print(f"  УВАГА: {len(data['code_conflicts'])} збігів коду з різним кольором (змішані каталоги?)")
    return 0


def reopen(folder: str, out: str | None, force: bool) -> int:
    from .export.package import build_package
    try:
        res = open_project(folder)
    except ProjectError as e:
        print(f"Помилка проєкту: {e}", file=sys.stderr)
        return 2
    sm, t = summarize(res.warnings), res.spec["totals"]
    print(f"Проєкт відкрито: {res.original_name}, ділянок {res.report['regions_final']}, кольорів {t['paints']}, "
          f"ємностей {t['containers']}; попередження: критичних {sm['critical']}, звичайних {sm['warning']}")
    if out:
        info = build_package(res, out, res.source_photo, force=force, original_name=res.original_name)
        print(f"Пакет збережено: {info['dir']}" + (" (виробничі файли заблоковано)" if info["blocked"] else ""))
        return 2 if info["blocked"] else 0
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
