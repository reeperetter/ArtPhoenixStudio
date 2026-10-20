from __future__ import annotations

import argparse
import json
import sys

from .generate import generate
from .settings import PRESETS, Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paint-by-numbers", description="Фото -> картина за номерами (прототип, етап 1)")
    ap.add_argument("photo", help="шлях до фотографії")
    ap.add_argument("-o", "--out", default="out", help="папка результату")
    ap.add_argument("--mode", choices=list(PRESETS), default="balanced")
    ap.add_argument("--colors", type=int, default=None, help="кількість кольорів (4..64)")
    ap.add_argument("--width-mm", type=float, default=300.0)
    ap.add_argument("--height-mm", type=float, default=None)
    ap.add_argument("--px-per-mm", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=12345)
    a = ap.parse_args(argv)
    if a.colors is not None and not 4 <= a.colors <= 64:
        ap.error("--colors має бути в межах 4..64")
    s = Settings(mode=a.mode, n_colors=a.colors, width_mm=a.width_mm, height_mm=a.height_mm,
                 px_per_mm=a.px_per_mm, seed=a.seed)
    res = generate(a.photo, s, a.out)
    print(json.dumps(res.report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
