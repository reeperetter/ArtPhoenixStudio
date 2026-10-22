"""Номери з виносками (розділ 9.3 ТЗ): ділянки, у які номер не вміщається, отримують номер у
найближчому вільному місці й тонку лінію-виноску з крапкою всередині ділянки.

Класичний алгоритм без ШІ: карта відстаней до ліній контуру + карта зайнятості; кандидати
перебираються кільцями навколо ділянки, обирається найближчий із найменшою кількістю перетинів
ліній. Детерміновано."""
from __future__ import annotations

import math

import cv2
import numpy as np

MAX_LEADER_MM = 12.0       # найбільша довжина виноски
RING_STEP_MM = 0.5
N_ANGLES = 24
CROSS_PENALTY_MM = 4.0     # штраф за кожен перетин лінії контуру (в мм довжини)
TOP_CANDIDATES = 40
SCALE = 2                  # растр ліній вдвічі точніший за робочий


def _half_diag(h: float, nd: int) -> float:
    return 0.5 * math.sqrt((0.62 * nd * h) ** 2 + h * h)


def place_leaders(spots, chains, shape: tuple[int, int], min_digit_px: float, line_px: float,
                  px_per_mm: float, max_mm: float = MAX_LEADER_MM) -> dict:
    """Змінює `spots` на місці. Повертає {"placed": n, "failed": [region, ...]}."""
    H, W = shape
    todo = [s for s in spots if s.digit_px <= 0]
    if not todo:
        return {"placed": 0, "failed": []}

    # растр ліній контуру й відстань від кожної точки до найближчої лінії (px робочого полотна)
    lines = np.zeros((H * SCALE, W * SCALE), np.uint8)
    th = max(1, int(round(line_px * SCALE)))
    for ch in chains:
        pts = np.round(ch.pts * SCALE * 16).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(lines, [pts], False, 1, th, cv2.LINE_8, shift=4)
    free = cv2.distanceTransform((lines == 0).astype(np.uint8), cv2.DIST_L2, 3) / SCALE

    # зайнятість: «num» --- місця, де не можна ставити центр нового номера; «glyph» --- де не можна проводити лінію
    forbid = np.zeros((H, W), np.uint8)
    glyph = np.zeros((H, W), np.uint8)
    for s in spots:
        if s.digit_px > 0:
            hd = _half_diag(s.digit_px, len(str(s.number)))
            _stamp(glyph, s.x, s.y, hd + 0.5)
            _stamp(forbid, s.x, s.y, hd + _half_diag(min_digit_px, 2) + line_px)
    for s in todo:                     # крапки-якорі теж резервуються
        _stamp(forbid, s.x, s.y, line_px * 2 + _half_diag(min_digit_px, 2))

    d0 = 0.0
    step = RING_STEP_MM * px_per_mm
    dmax = max_mm * px_per_mm
    ang = np.arange(N_ANGLES) * (2 * math.pi / N_ANGLES)
    ca, sa = np.cos(ang), np.sin(ang)
    placed, failed = 0, []

    for s in sorted(todo, key=lambda q: (q.y, q.x, q.region)):
        nd = len(str(s.number))
        hd = _half_diag(min_digit_px, nd)
        need = hd + line_px / 2.0 + 0.3          # вільне місце навколо центра номера
        radii = np.arange(max(hd, step), dmax + 1e-6, step)
        cx = (s.x + radii[:, None] * ca[None, :]).ravel()
        cy = (s.y + radii[:, None] * sa[None, :]).ravel()
        dist = np.repeat(radii, N_ANGLES)
        ix, iy = np.round(cx).astype(int), np.round(cy).astype(int)
        inside = (ix >= 0) & (iy >= 0) & (ix < W) & (iy < H) & \
                 (cx - need >= 0) & (cy - need >= 0) & (cx + need <= W) & (cy + need <= H)
        ok = np.zeros(cx.shape, bool)
        k = np.flatnonzero(inside)
        fx, fy = np.round(cx[k] * SCALE).astype(int), np.round(cy[k] * SCALE).astype(int)
        fx = np.clip(fx, 0, W * SCALE - 1)
        fy = np.clip(fy, 0, H * SCALE - 1)
        ok[k] = (free[fy, fx] >= need) & (forbid[iy[k], ix[k]] == 0)
        cand = np.flatnonzero(ok)
        best, best_score = None, None
        for j in cand[:TOP_CANDIDATES]:           # кандидати вже впорядковані за зростанням відстані
            x1, y1 = float(cx[j]), float(cy[j])
            cross, hits = _walk(lines, glyph, s.x, s.y, x1, y1, hd)
            if hits:
                continue
            score = dist[j] + cross * CROSS_PENALTY_MM * px_per_mm
            if best_score is None or score < best_score:
                best, best_score = (x1, y1), score
        if best is None:
            failed.append(s.region)
            continue
        x1, y1 = best
        vx, vy = s.x - x1, s.y - y1
        n = math.hypot(vx, vy) or 1.0
        s.anchor = (s.x, s.y)
        s.lead_from = (x1 + vx / n * hd, y1 + vy / n * hd)
        s.x, s.y, s.digit_px = x1, y1, float(min_digit_px)
        _stamp(forbid, x1, y1, hd + _half_diag(min_digit_px, 2) + line_px)
        _stamp(glyph, x1, y1, hd + 0.5)
        placed += 1
    return {"placed": placed, "failed": failed}


def _stamp(m: np.ndarray, x: float, y: float, r: float) -> None:
    cv2.circle(m, (int(round(x)), int(round(y))), int(math.ceil(r)), 1, -1)


def _walk(lines: np.ndarray, glyph: np.ndarray, x0, y0, x1, y1, skip_end: float) -> tuple[int, bool]:
    """Кількість перетинів ліній контуру вздовж виноски та чи зачіпає вона чужі цифри."""
    H, W = glyph.shape
    n = max(2, int(math.hypot(x1 - x0, y1 - y0) * SCALE))
    t = np.linspace(0.0, 1.0, n)
    px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
    gx, gy = np.clip(np.round(px).astype(int), 0, W - 1), np.clip(np.round(py).astype(int), 0, H - 1)
    keep = np.hypot(px - x1, py - y1) > skip_end          # кінець біля власного номера не перевіряємо
    hits = bool(glyph[gy, gx][keep].any())
    lx, ly = np.clip(np.round(px * SCALE).astype(int), 0, lines.shape[1] - 1), \
        np.clip(np.round(py * SCALE).astype(int), 0, lines.shape[0] - 1)
    on = lines[ly, lx].astype(np.int8)
    cross = int(((on[1:] == 1) & (on[:-1] == 0)).sum())
    return cross, hits
