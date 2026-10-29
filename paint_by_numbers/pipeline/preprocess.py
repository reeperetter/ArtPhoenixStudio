"""Згладжування зі збереженням меж, колірний простір Lab, карта значущості (без ШІ)."""
from __future__ import annotations

import cv2
import numpy as np


def denoise(bgr: np.ndarray, iterations: int) -> np.ndarray:
    out = bgr
    for _ in range(max(1, iterations)):
        out = cv2.bilateralFilter(out, d=9, sigmaColor=35, sigmaSpace=7)
    return out


def denoise_zoned(bgr: np.ndarray, iterations: int, unit: np.ndarray | None) -> np.ndarray:
    """Згладжування слабшає в зонах пріоритету (там лишаються дрібніші деталі)."""
    heavy = denoise(bgr, iterations)
    if unit is None or not unit.any():
        return heavy
    # у зоні пріоритету лишається лише дуже легке згладжування: дрібні деталі (очі, губи, зморшки) не розмиваються
    light = cv2.bilateralFilter(bgr, d=5, sigmaColor=18, sigmaSpace=3)
    u = unit[..., None]
    return np.clip(light.astype(np.float32) * u + heavy.astype(np.float32) * (1.0 - u) + 0.5, 0, 255).astype(np.uint8)


def to_lab(bgr: np.ndarray) -> np.ndarray:
    """float32 Lab (L 0..100, a/b приблизно -127..127)."""
    f = bgr.astype(np.float32) / 255.0
    return cv2.cvtColor(f, cv2.COLOR_BGR2Lab)


def lab_to_bgr_u8(lab: np.ndarray) -> np.ndarray:
    bgr = cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_Lab2BGR)
    return np.clip(bgr * 255.0 + 0.5, 0, 255).astype(np.uint8)


def saliency_map(bgr: np.ndarray) -> np.ndarray:
    """Значущість 0..1 за локальним контрастом і щільністю меж. Класичний метод,
    без розпізнавання об'єктів."""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 1.5)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    density = cv2.GaussianBlur(mag, (0, 0), 6.0)
    hi = float(np.percentile(density, 95)) or 1.0
    return np.clip(density / hi, 0.0, 1.0)


def skin_map(bgr: np.ndarray, min_blob_frac: float = 0.004) -> np.ndarray:
    """М'яка карта «схоже на шкіру» 0..1 за кольором (YCrCb) --- класичний поріг, без розпізнавання облич.
    Лишаються лише достатньо великі суцільні плями (обличчя, руки), щоб поодинокі крапки не рахувалися;
    уздовж країв пляма розмивається. Хибні спрацювання (пісок, дерево) лише додають там деталізації."""
    ycc = cv2.cvtColor(cv2.GaussianBlur(bgr, (0, 0), 2.0), cv2.COLOR_BGR2YCrCb)
    y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    m = ((cr >= 135) & (cr <= 175) & (cb >= 80) & (cb <= 128) & (y >= 40)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_blob_frac * m.size
    m = keep[lab].astype(np.float32)
    k = max(3, int(min(bgr.shape[:2]) * 0.03)) | 1
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))      # очі, брови, губи лежать у плямі шкіри
    return np.clip(cv2.GaussianBlur(m, (0, 0), k / 3.0), 0.0, 1.0)
