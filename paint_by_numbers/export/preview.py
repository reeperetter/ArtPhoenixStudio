"""Растрові перегляди: кольоровий еталон і контурний макет з номерами (прототип).
Остаточний векторний макет (SVG/PDF) буде створено на етапі 2--4."""
from __future__ import annotations

import math
import cv2
import numpy as np
from scipy import ndimage as ndi

from ..geometry.labels import NumberSpot, digit_height
from ..pipeline.preprocess import lab_to_bgr_u8
from ..pipeline.regions import RegionMap


def palette_bgr(rm: RegionMap) -> np.ndarray:
    return lab_to_bgr_u8(rm.palette_lab[None, :, :])[0]


def render_color(rm: RegionMap) -> np.ndarray:
    pal = palette_bgr(rm)
    return pal[rm.color[rm.labels]]


def boundary_mask(L: np.ndarray) -> np.ndarray:
    m = np.zeros(L.shape, bool)
    d = L[:, :-1] != L[:, 1:]
    m[:, :-1] |= d
    m[:, 1:] |= d
    d = L[:-1, :] != L[1:, :]
    m[:-1, :] |= d
    m[1:, :] |= d
    return m


def place_numbers(rm: RegionMap, min_digit_px: float, max_digit_px: float, line_px: float) -> list[NumberSpot]:
    """Номер ставиться в точці, найбільш віддаленій від межі (distance transform).
    Центроїд не використовується: він може лежати поза увігнутою областю."""
    L = rm.labels
    objs = ndi.find_objects(L + 1)
    spots: list[NumberSpot] = []
    for i, sl in enumerate(objs):
        if sl is None:
            continue
        mask = (L[sl] == i).astype(np.uint8)
        padded = np.pad(mask, 1)
        dt = cv2.distanceTransform(padded, cv2.DIST_L2, 3)
        j = int(np.argmax(dt))
        yy, xx = divmod(j, dt.shape[1])
        r = float(dt[yy, xx]) - line_px / 2.0
        y = sl[0].start + yy - 1
        x = sl[1].start + xx - 1
        n_digits = len(str(int(rm.color[i]) + 1))
        spots.append(NumberSpot(i, int(rm.color[i]) + 1, x, y, r,
                                digit_height(r, n_digits, min_digit_px, max_digit_px)))
    return spots


def render_vector(chains, shape: tuple[int, int], spots: list[NumberSpot], scale: int,
                  line_px: float, tint: np.ndarray | None = None) -> np.ndarray:
    """Растеризація саме векторних ребер (того, що потрапляє в SVG), з підпіксельною точністю."""
    H, W = shape
    img = np.full((H * scale, W * scale, 3), 255, np.uint8)
    if tint is not None:       # світла заливка кольором під контурами (numbered_preview)
        up = cv2.resize(tint, (W * scale, H * scale), interpolation=cv2.INTER_NEAREST)
        img = (up.astype(np.float32) * 0.35 + 255 * 0.65).astype(np.uint8)
    th = max(1, int(round(line_px * scale)))
    for ch in chains:
        pts = np.round(ch.pts * scale * 16).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [pts], False, (40, 40, 40), th, cv2.LINE_AA, shift=4)
    _draw_numbers(img, spots, scale)
    return img


def render_contours(rm: RegionMap, spots: list[NumberSpot], scale: int, line_px: float) -> np.ndarray:
    H, W = rm.labels.shape
    Ls = cv2.resize(rm.labels, (W * scale, H * scale), interpolation=cv2.INTER_NEAREST)
    bm = boundary_mask(Ls).astype(np.uint8)
    k = max(1, int(round(line_px * scale)))
    if k > 1:
        bm = cv2.dilate(bm, np.ones((k, k), np.uint8))
    img = np.full((H * scale, W * scale, 3), 255, np.uint8)
    img[bm > 0] = (40, 40, 40)
    _draw_numbers(img, spots, scale)
    return img


def _draw_numbers(img: np.ndarray, spots: list[NumberSpot], scale: int) -> None:
    (_, base_h), _ = cv2.getTextSize("0", cv2.FONT_HERSHEY_SIMPLEX, 1.0, 1)
    for s in spots:
        if s.digit_px <= 0:
            continue
        text = str(s.number)
        fs = (s.digit_px * scale) / (base_h if base_h else 22)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
        org = (int(s.x * scale - tw / 2), int(s.y * scale + th / 2))
        cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, fs, (90, 90, 90), 1, cv2.LINE_AA)


def render_palette(rm: RegionMap, px_per_region: np.ndarray | None = None) -> np.ndarray:
    pal = palette_bgr(rm)
    k = len(pal)
    cell = 60
    cols = min(k, 8)
    rows = math.ceil(k / cols)
    img = np.full((rows * cell, cols * cell, 3), 255, np.uint8)
    for i, c in enumerate(pal):
        r, q = divmod(i, cols)
        cv2.rectangle(img, (q * cell + 4, r * cell + 4), (q * cell + cell - 4, r * cell + cell - 4), tuple(int(v) for v in c), -1)
        lum = int(c[0]) * 0.114 + int(c[1]) * 0.587 + int(c[2]) * 0.299
        cv2.putText(img, str(i + 1), (q * cell + 10, r * cell + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (255, 255, 255) if lum < 128 else (0, 0, 0), 1, cv2.LINE_AA)
    return img


def compare_panel(orig: np.ndarray, color: np.ndarray, contours: np.ndarray, height: int = 900) -> np.ndarray:
    def fit(im):
        h, w = im.shape[:2]
        return cv2.resize(im, (int(w * height / h), height), interpolation=cv2.INTER_AREA)
    return np.hstack([fit(orig), fit(color), fit(contours)])
