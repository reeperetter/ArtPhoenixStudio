"""Квантування кольорів у Lab: класичний K-Means із фіксованою ініціалізацією."""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans


def select_from_stock(train: np.ndarray, sw: np.ndarray | None, stock: np.ndarray, k: int, max_pass: int = 12) -> np.ndarray:
    """Індекси k кольорів зі складу, що мінімізують зважену суму квадратів відстаней у Lab до пікселів фото.
    Жадібний набір + обмін (k-медоїди на кінцевій множині кольорів); повністю детермінований."""
    k = min(k, len(stock))
    w = np.ones(len(train)) if sw is None else np.asarray(sw, np.float64)
    D = ((train[:, None, :].astype(np.float64) - stock[None, :, :].astype(np.float64)) ** 2).sum(2)
    chosen: list[int] = []
    cur = np.full(len(train), np.inf)
    for _ in range(k):
        cost = (w[:, None] * np.minimum(cur[:, None], D)).sum(0)
        cost[chosen] = np.inf
        j = int(np.argmin(cost))
        chosen.append(j)
        cur = np.minimum(cur, D[:, j])
    for _ in range(max_pass):
        improved = False
        for pos in range(k):
            rest = chosen[:pos] + chosen[pos + 1:]
            base = D[:, rest].min(1) if rest else np.full(len(train), np.inf)
            cost = (w[:, None] * np.minimum(base[:, None], D)).sum(0)
            cost[rest] = np.inf
            j = int(np.argmin(cost))
            if j != chosen[pos] and cost[j] < cost[chosen[pos]] - 1e-9:
                chosen[pos] = j
                improved = True
        if not improved:
            break
    return np.array(sorted(chosen))


def quantize(lab: np.ndarray, k: int, seed: int, sample: int = 150_000, weights: np.ndarray | None = None,
             stock: np.ndarray | None = None):
    """Повертає (labels HxW int32, centers kx3 float32). weights --- вага пікселів HxW
    (зони пріоритету отримують більше кольорів палітри)."""
    h, w, _ = lab.shape
    flat = lab.reshape(-1, 3)
    rng = np.random.default_rng(seed)
    wflat = None if weights is None else weights.ravel()
    if flat.shape[0] > sample:
        idx = rng.choice(flat.shape[0], sample, replace=False)
        train = flat[idx]
        sw = None if wflat is None else wflat[idx]
    else:
        train = flat
        sw = wflat
    if stock is not None:                  # фіксована палітра: кольори беруться з готового складу фарб
        stock = np.asarray(stock, np.float32)
        sub = train if len(train) <= 20_000 else train[rng.choice(len(train), 20_000, replace=False)]
        subw = None if sw is None else (sw if len(train) <= 20_000 else None)
        chosen = select_from_stock(sub, subw, stock, k)
        centers = stock[chosen]
        d = ((flat[:, None, :] - centers[None, :, :]) ** 2).sum(2) if flat.shape[0] <= 50_000 else None
        if d is None:
            labels = np.concatenate([((flat[i:i + 50_000, None, :] - centers[None]) ** 2).sum(2).argmin(1)
                                     for i in range(0, flat.shape[0], 50_000)])
        else:
            labels = d.argmin(1)
        return labels.astype(np.int32).reshape(h, w), centers.astype(np.float32)
    km = KMeans(n_clusters=k, n_init=3, random_state=seed)
    km.fit(train, sample_weight=sw)
    labels = km.predict(flat).astype(np.int32).reshape(h, w)
    return labels, km.cluster_centers_.astype(np.float32)
