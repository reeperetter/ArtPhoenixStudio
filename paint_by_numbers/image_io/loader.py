"""Завантаження фото: орієнтація за EXIF, кадрування під пропорції полотна, робоча копія."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass
class LoadedImage:
    bgr: np.ndarray            # робоча копія uint8 BGR
    src_size: tuple[int, int]  # (w, h) оригіналу після EXIF
    work_size: tuple[int, int]
    width_mm: float
    height_mm: float
    px_per_mm: float
    warnings: list[str]


def load_image(path: str, width_mm: float, height_mm: float | None, px_per_mm: float) -> LoadedImage:
    warnings: list[str] = []
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)           # правильна орієнтація за EXIF
    if im.mode in ("RGBA", "LA", "P"):         # прозорість -> білий фон
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    sw, sh = im.size

    if height_mm is None:
        height_mm = width_mm * sh / sw
    # центральне кадрування під пропорції полотна
    target = width_mm / height_mm
    cur = sw / sh
    if abs(cur - target) > 0.01:
        if cur > target:
            nw = int(round(sh * target))
            x0 = (sw - nw) // 2
            im = im.crop((x0, 0, x0 + nw, sh))
        else:
            nh = int(round(sw / target))
            y0 = (sh - nh) // 2
            im = im.crop((0, y0, sw, y0 + nh))
        warnings.append("Фото обрізано до пропорцій полотна (центральне кадрування).")

    ww, wh = int(round(width_mm * px_per_mm)), int(round(height_mm * px_per_mm))
    cw, ch = im.size
    if cw < ww:
        warnings.append(
            f"Роздільна здатність фото низька для цього розміру полотна: "
            f"{cw}x{ch} px проти робочих {ww}x{wh} px."
        )
    arr = np.asarray(im)
    interp = cv2.INTER_AREA if cw >= ww else cv2.INTER_CUBIC
    arr = cv2.resize(arr, (ww, wh), interpolation=interp)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return LoadedImage(bgr, (sw, sh), (ww, wh), width_mm, height_mm, px_per_mm, warnings)
