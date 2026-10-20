"""Зв'язні області, граф сусідства та контрольоване об'єднання малих областей (розділи 7.5, 7.6, 7.9)."""
from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi


@dataclass
class RegionMap:
    labels: np.ndarray        # HxW int32, компактні id областей 0..R-1
    color: np.ndarray         # R, індекс кольору палітри (0..K'-1, K' <= K)
    area_px: np.ndarray       # R
    palette_lab: np.ndarray   # K' x 3, середній колір за фактичними пікселями
    n_before: int             # кількість областей до об'єднання


def connected_regions(color_labels: np.ndarray, k: int):
    h, w = color_labels.shape
    out = np.zeros((h, w), np.int32)
    colors: list[int] = []
    nxt = 0
    for c in range(k):
        m = color_labels == c
        if not m.any():
            continue
        lab, n = ndi.label(m)                 # 4-зв'язність
        out[m] = lab[m] - 1 + nxt
        colors.extend([c] * n)
        nxt += n
    return out, np.asarray(colors, np.int32)


def _adjacency(L: np.ndarray, R: int):
    parts = []
    for a, b in ((L[:, :-1], L[:, 1:]), (L[:-1, :], L[1:, :])):
        m = a != b
        lo = np.minimum(a[m], b[m]).astype(np.int64)
        hi = np.maximum(a[m], b[m]).astype(np.int64)
        parts.append(lo * R + hi)
    keys, counts = np.unique(np.concatenate(parts), return_counts=True)
    return keys // R, keys % R, counts


def merge_small_regions(
    L: np.ndarray,
    color: np.ndarray,
    lab: np.ndarray,
    importance: np.ndarray,
    base_min_px: float,
    importance_relief: float = 0.5,
    forced: np.ndarray | None = None,
    keep_contrast: float | None = None,
    n_before: int | None = None,
) -> RegionMap:
    """Малі області приєднуються до найбільш відповідного сусіда (колір + спільна межа).
    Поріг площі нижчий там, де значущість висока. Сусідні області одного кольору зливаються."""
    R = int(L.max()) + 1
    flat = L.ravel()
    area = np.bincount(flat, minlength=R).astype(np.float64)
    sumlab = np.stack(
        [np.bincount(flat, weights=lab[..., i].ravel(), minlength=R) for i in range(3)], axis=1
    )
    sumimp = np.bincount(flat, weights=importance.ravel(), minlength=R)
    col = color.copy()
    force = np.zeros(R, bool) if forced is None else forced.copy()

    adj: list[dict] = [dict() for _ in range(R)]
    lo, hi, cnt = _adjacency(L, R)
    for a, b, n in zip(lo.tolist(), hi.tolist(), cnt.tolist()):
        adj[a][b] = n
        adj[b][a] = n

    parent = np.arange(R)
    alive = np.ones(R, bool)

    def thr(r: int) -> float:
        return base_min_px * (1.0 - importance_relief * sumimp[r] / area[r])

    def absorb(keep: int, gone: int) -> None:
        area[keep] += area[gone]
        sumlab[keep] += sumlab[gone]
        sumimp[keep] += sumimp[gone]
        for m, b in adj[gone].items():
            if m == keep:
                continue
            adj[keep][m] = adj[keep].get(m, 0) + b
            adj[m][keep] = adj[m].get(keep, 0) + b
            del adj[m][gone]
        adj[keep].pop(gone, None)
        adj[gone] = {}
        alive[gone] = False
        parent[gone] = keep

    def fuse(r: int) -> int:
        """Зливає сусідні області того самого кольору (межа між ними не має сенсу)."""
        while True:
            same = [m for m in adj[r] if col[m] == col[r]]
            if not same:
                return r
            for m in same:
                if not alive[m] or m == r:
                    continue
                keep, gone = (m, r) if area[m] > area[r] else (r, m)
                absorb(keep, gone)
                r = keep

    heap = [(area[r], r) for r in range(R) if force[r] or area[r] < thr(r)]
    heapq.heapify(heap)
    while heap:
        a, r = heapq.heappop(heap)
        if not alive[r] or a != area[r] or not (force[r] or area[r] < thr(r)) or not adj[r]:
            continue
        total = float(sum(adj[r].values()))
        mr = sumlab[r] / area[r]
        best, best_cost, dmin = -1, np.inf, np.inf
        for m, b in adj[r].items():
            d = float(np.linalg.norm(mr - sumlab[m] / area[m]))
            dmin = min(dmin, d)
            cost = d * (1.0 - 0.5 * b / total)
            if cost < best_cost:
                best, best_cost = m, cost
        # примусово об'єднувана ділянка, що різко контрастує з усіма сусідами (зіниця, риса обличчя),
        # лишається: її буде вирішено геометрією або позначено у звіті
        if keep_contrast is not None and force[r] and area[r] >= thr(r) and dmin >= keep_contrast:
            continue
        col[r] = col[best]
        absorb(best, r)
        s = fuse(best)
        if area[s] < thr(s):
            heapq.heappush(heap, (area[s], s))

    root = parent.copy()
    while True:
        nxt = root[root]
        if np.array_equal(nxt, root):
            break
        root = nxt
    ids = np.flatnonzero(alive)
    newid = -np.ones(R, np.int64)
    newid[ids] = np.arange(len(ids))
    final_L = newid[root][L].astype(np.int32)

    f_col, f_area, f_sum = col[ids], area[ids], sumlab[ids]
    used = np.unique(f_col)
    remap = -np.ones(int(f_col.max()) + 1, np.int64)
    pal_area = np.array([f_area[f_col == c].sum() for c in used])
    order = np.argsort(-pal_area)                # нумерація: від найбільшої площі
    remap[used[order]] = np.arange(len(used))
    palette = np.stack(
        [f_sum[f_col == c].sum(axis=0) / f_area[f_col == c].sum() for c in used[order]]
    ).astype(np.float32)
    return RegionMap(final_L, remap[f_col].astype(np.int32), f_area.astype(np.int64), palette,
                     R if n_before is None else n_before)


def remove_protrusions(L: np.ndarray, radius_px: float, sal: np.ndarray, keep_sal: float = 0.75) -> np.ndarray:
    """Прибирає вузькі виступи й перемички шириною менше 2*radius_px (морфологічне розкриття кожної
    області). Вилучені пікселі переходять до найближчої області, що збереглася. У зонах високої
    значущості (sal >= keep_sal) нічого не змінюється. Результат може мати розірвані області:
    після нього потрібно повторити виділення зв'язних компонент."""
    from scipy import ndimage as ndi
    r = int(round(radius_px))
    if r < 1:
        return L
    kernel = cv2_ellipse(2 * r + 1)
    objs = ndi.find_objects(L + 1)
    lost = np.zeros(L.shape, bool)
    H, W = L.shape
    import cv2
    for i, sl in enumerate(objs):
        if sl is None:
            continue
        y0, y1 = max(sl[0].start - r - 1, 0), min(sl[0].stop + r + 1, H)
        x0, x1 = max(sl[1].start - r - 1, 0), min(sl[1].stop + r + 1, W)
        m = (L[y0:y1, x0:x1] == i).astype(np.uint8)
        if m.shape[0] < 2 * r + 1 or m.shape[1] < 2 * r + 1:
            lost[y0:y1, x0:x1] |= m.astype(bool)
            continue
        # полотно як «стіна»: розкриття не повинно різати область біля краю зображення
        padded = np.pad(m, r, mode="edge") if (y0 == 0 or x0 == 0 or y1 == H or x1 == W) else m
        op = cv2.morphologyEx(padded, cv2.MORPH_OPEN, kernel)
        if padded is not m:
            op = op[r:-r, r:-r]
        lost[y0:y1, x0:x1] |= (m > 0) & (op == 0)
    lost &= sal < keep_sal
    if not lost.any():
        return L
    keep = ~lost
    if not keep.any():
        return L
    _, (iy, ix) = ndi.distance_transform_edt(lost, return_indices=True)
    out = L.copy()
    out[lost] = L[iy[lost], ix[lost]]
    return out


def cv2_ellipse(size: int) -> np.ndarray:
    import cv2
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
