"""Планарне розбиття зі спільними ребрами (розділ 7.10 ТЗ).

Межі між областями виділяються з растра як ламані на ґратці кутів пікселів. Кожна спільна межа
існує в єдиному екземплярі (ребро розбиття). Згладжування й спрощення застосовуються до ребер, а
не до полігонів, причому вузли (де сходяться три й більше областей) нерухомі. Тому сусідні області
за побудовою не мають щілин і накладань. Результат перевіряється (розділи 7.13, 13.2 ТЗ)."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
import shapely
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import LineString, Polygon
from shapely.ops import polylabel
from shapely.strtree import STRtree


@dataclass
class Chain:
    raw: np.ndarray                 # Nx2 float64, вершини ґратки (x=стовпець, y=рядок)
    closed: bool
    pair: tuple[int, int]           # мітки областей по обидва боки; -1 --- поза полотном
    importance: float               # середня значущість уздовж ребра 0..1
    pts: np.ndarray = None          # фінальна ламана
    raw_mode: bool = False          # True --- без згладжування (запасний варіант)

    @property
    def endpoints(self):
        return (tuple(self.raw[0]), tuple(self.raw[-1]))


@dataclass
class Geometry:
    chains: list[Chain]
    faces: dict[int, Polygon]       # id області -> полігон (в пікселях)
    topology: dict
    shape: tuple[int, int]          # (H, W)


# ------------------------------------------------------------------ виділення ребер

def extract_chains(L: np.ndarray, sal: np.ndarray) -> list[Chain]:
    H, W = L.shape
    P = np.pad(L, 1, constant_values=-1)
    stride = W + 1
    a = P[0:H + 1, 1:W + 1]
    b = P[1:H + 2, 1:W + 1]
    hi, hj = np.nonzero(a != b)
    c = P[1:H + 1, 0:W + 1]
    d = P[1:H + 1, 1:W + 2]
    vi, vj = np.nonzero(c != d)
    U = np.concatenate([hi * stride + hj, vi * stride + vj])
    V = np.concatenate([hi * stride + hj + 1, (vi + 1) * stride + vj])
    A = np.concatenate([a[hi, hj], c[vi, vj]])
    B = np.concatenate([b[hi, hj], d[vi, vj]])
    nseg = len(U)

    ends = np.concatenate([U, V])
    other = np.concatenate([V, U])
    sid = np.concatenate([np.arange(nseg), np.arange(nseg)])
    order = np.argsort(ends, kind="stable")
    other_l = other[order].tolist()
    sid_l = sid[order].tolist()
    deg = np.bincount(ends, minlength=(H + 1) * stride)
    ptr_l = np.concatenate([[0], np.cumsum(deg)]).tolist()
    deg_l = deg.tolist()
    A_l, B_l = A.tolist(), B.tolist()

    used = bytearray(nseg)
    paths: list[tuple[list[int], int, bool]] = []   # (кути, перший сегмент, замкнене)

    def step(cur: int, k: int):
        t = ptr_l[cur]
        t = t if sid_l[t] != k else t + 1
        return other_l[t], sid_l[t]

    for s in np.flatnonzero((deg != 2) & (deg > 0)).tolist():
        for t in range(ptr_l[s], ptr_l[s + 1]):
            k = sid_l[t]
            if used[k]:
                continue
            k0 = k
            used[k] = 1
            path = [s]
            cur = other_l[t]
            while deg_l[cur] == 2:
                path.append(cur)
                cur, k = step(cur, k)
                used[k] = 1
            path.append(cur)
            paths.append((path, k0, False))

    for k in range(nseg):                    # замкнені ребра без вузлів (острівці)
        if used[k]:
            continue
        start = int(U[k])
        used[k] = 1
        path = [start]
        cur, kk = int(V[k]), k
        while cur != start:
            path.append(cur)
            cur, kk = step(cur, kk)
            used[kk] = 1
        path.append(start)
        paths.append((path, k, True))

    chains = []
    sh, sw = sal.shape
    for path, k0, closed in paths:
        cs = np.asarray(path, np.int64)
        pts = np.column_stack([cs % stride, cs // stride]).astype(np.float64)
        ys = np.minimum(pts[:, 1].astype(int), sh - 1)
        xs = np.minimum(pts[:, 0].astype(int), sw - 1)
        imp = float(sal[ys, xs].mean())
        pair = tuple(sorted((A_l[k0], B_l[k0])))
        chains.append(Chain(pts, closed, pair, imp, raw_mode=(pair[0] == -1)))   # межа полотна лишається прямою
    return chains


# ------------------------------------------------------------------ згладжування та спрощення

def _smooth(pts: np.ndarray, closed: bool, sigma: float) -> np.ndarray:
    n = len(pts)
    if sigma <= 0 or n < 4:
        return pts
    if closed:
        p = pts[:-1]
        out = np.column_stack([gaussian_filter1d(p[:, i], sigma, mode="wrap") for i in range(2)])
        return np.vstack([out, out[:1]])
    pad = min(int(3 * sigma) + 1, n - 1)
    head = 2 * pts[0] - pts[pad:0:-1]
    tail = 2 * pts[-1] - pts[-2:-pad - 2:-1]
    ext = np.vstack([head, pts, tail])
    sm = np.column_stack([gaussian_filter1d(ext[:, i], sigma, mode="nearest") for i in range(2)])
    out = sm[pad:pad + n].copy()
    out[0], out[-1] = pts[0], pts[-1]        # вузли нерухомі
    return out


def _simplify(pts: np.ndarray, closed: bool, eps: float) -> np.ndarray:
    n = len(pts)
    if n <= 3:
        return pts
    if closed:
        ap = cv2.approxPolyDP(pts[:-1].astype(np.float32).reshape(-1, 1, 2), eps, True)
        ap = ap.reshape(-1, 2).astype(np.float64)
        if len(ap) < 3:
            return pts
        return np.vstack([ap, ap[:1]])
    ap = cv2.approxPolyDP(pts.astype(np.float32).reshape(-1, 1, 2), eps, False)
    ap = ap.reshape(-1, 2).astype(np.float64)
    # вузли мають лишитися точно на місці (OpenCV для ребер, що починаються й закінчуються в одному
    # вузлі, може повернути іншу кінцеву точку)
    if not np.array_equal(ap[0], pts[0]):
        ap = np.vstack([pts[:1], ap])
    if not np.array_equal(ap[-1], pts[-1]):
        ap = np.vstack([ap, pts[-1:]])
    return ap


def process_chain(ch: Chain, sigma: float, sigma_important: float, eps: float, eps_important: float,
                  important_thr: float) -> None:
    if ch.raw_mode:
        ch.pts = _simplify(ch.raw, ch.closed, 0.0)
        return
    imp = ch.importance >= important_thr
    sg = sigma_important if imp else sigma
    ep = eps_important if imp else eps
    sm = _smooth(ch.raw, ch.closed, sg)
    ch.pts = _simplify(sm, ch.closed, ep)
    if ch.closed and len(ch.pts) < 4:
        ch.pts = _simplify(ch.raw, True, 0.0)


# ------------------------------------------------------------------ перевірка топології

def _bad_chains(chains: list[Chain]) -> set[int]:
    geoms = np.array([LineString(c.pts) if len(c.pts) >= 2 else LineString() for c in chains], dtype=object)
    bad: set[int] = set(np.flatnonzero(~shapely.is_simple(geoms)).tolist())
    tree = STRtree(geoms)
    qi, ti = tree.query(geoms, predicate="intersects")
    m = qi < ti
    qi, ti = qi[m], ti[m]
    if len(qi) == 0:
        return bad
    inter = shapely.intersection(geoms[qi], geoms[ti])
    for i, j, g in zip(qi.tolist(), ti.tolist(), inter):
        if g.is_empty:
            continue
        ok = shapely.get_type_id(g) in (0, 4)           # лише точки
        if ok:
            ends = {tuple(map(float, c)) for c in (chains[i].pts[0], chains[i].pts[-1])}
            ends2 = {tuple(map(float, c)) for c in (chains[j].pts[0], chains[j].pts[-1])}
            for xy in shapely.get_coordinates(g).tolist():
                t = (float(xy[0]), float(xy[1]))
                if t not in ends or t not in ends2:
                    ok = False
                    break
        if not ok:
            bad.add(i)
            bad.add(j)
    return bad


def build_geometry(L: np.ndarray, sal: np.ndarray, *, sigma=2.0, sigma_important=1.0, eps=0.5,
                   eps_important=0.3, important_thr=0.6, max_rounds=6) -> Geometry:
    H, W = L.shape
    R = int(L.max()) + 1
    chains = extract_chains(L, sal)
    for ch in chains:
        process_chain(ch, sigma, sigma_important, eps, eps_important, important_thr)

    fallback = 0
    rounds = 0
    for rounds in range(1, max_rounds + 1):
        bad = _bad_chains(chains)
        if not bad:
            break
        for i in bad:
            if not chains[i].raw_mode:
                chains[i].raw_mode = True
                process_chain(chains[i], sigma, sigma_important, eps, eps_important, important_thr)
                fallback += 1
    else:
        bad = _bad_chains(chains)

    # перевірка: кількість граней, площа, відповідність міткам (розділ 13.2 ТЗ)
    lines = [LineString(c.pts) for c in chains]
    faces_gc = shapely.polygonize(lines)
    faces = list(faces_gc.geoms)
    faces_by_label: dict[int, Polygon] = {}
    conflicts = 0
    for f in faces:
        pole = polylabel(f, 0.5)
        lab = int(L[min(int(pole.y), H - 1), min(int(pole.x), W - 1)])
        if lab in faces_by_label:
            conflicts += 1
        faces_by_label[lab] = f
    area_total = float(sum(f.area for f in faces))
    topo = {
        "chains": len(chains),
        "vertices_raw": int(sum(len(c.raw) for c in chains)),
        "vertices_final": int(sum(len(c.pts) for c in chains)),
        "chains_raw_fallback": fallback,
        "repair_rounds": rounds,
        "unresolved_crossings": len(bad),
        "faces": len(faces),
        "regions": R,
        "label_conflicts": conflicts,
        "missing_regions": sorted(set(range(R)) - set(faces_by_label))[:20],
        "area_error_px": round(area_total - H * W, 6),
        "ok": (not bad and len(faces) == R and conflicts == 0 and abs(area_total - H * W) < 1e-6
               and len(faces_by_label) == R),
    }
    return Geometry(chains, faces_by_label, topo, (H, W))
