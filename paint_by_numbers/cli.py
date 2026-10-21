from __future__ import annotations

import argparse
import sys

from .generate import generate
from .quality.warnings import summarize
from .settings import PRESETS, Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paint-by-numbers",
                                 description="Фото -> виробничий пакет картини за номерами")
    ap.add_argument("photo", help="шлях до фотографії")
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
    ap.add_argument("--force", action="store_true", help="сформувати пакет попри критичні помилки")
    a = ap.parse_args(argv)
    if a.colors is not None and not 4 <= a.colors <= 64:
        ap.error("--colors має бути в межах 4..64")
    if a.safety_factor < 1:
        ap.error("--safety-factor має бути >= 1")
    s = Settings(mode=a.mode, n_colors=a.colors, width_mm=a.width_mm, height_mm=a.height_mm,
                 px_per_mm=a.px_per_mm, seed=a.seed, order_number=a.order, project_name=a.name,
                 coverage_mm2_per_container=a.coverage_mm2, safety_factor=a.safety_factor,
                 coverage_confirmed=a.coverage_confirmed)
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


if __name__ == "__main__":
    sys.exit(main())
