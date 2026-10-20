"""Згладжування зі збереженням меж, колірний простір Lab, карта значущості (без ШІ)."""
from __future__ import annotations

import cv2
import numpy as np


def denoise(bgr: np.ndarray, iterations: int) -> np.ndarray:
    out = bgr
    for _ in range(max(1, iterations)):
        out = cv2.bilateralFilter(out, d=9, sigmaColor=35, sigmaSpace=7)
    return out


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
