"""Квантування кольорів у Lab: класичний K-Means із фіксованою ініціалізацією."""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans


def quantize(lab: np.ndarray, k: int, seed: int, sample: int = 150_000, weights: np.ndarray | None = None):
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
    km = KMeans(n_clusters=k, n_init=3, random_state=seed)
    km.fit(train, sample_weight=sw)
    labels = km.predict(flat).astype(np.int32).reshape(h, w)
    return labels, km.cluster_centers_.astype(np.float32)
