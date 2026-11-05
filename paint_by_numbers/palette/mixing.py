"""Підбір рецептів змішування кольорів із обмеженого набору базових фарб.

Модель: одноконстантна теорія Кубелки--Мунка (Kubelka--Munk) окремо для каналів лінійного RGB:
    K/S = (1 - R)^2 / (2 R),  суміш: (K/S)_mix = сума частка_i * сила_i * (K/S)_i,  R = 1 + K/S - sqrt((K/S)^2 + 2 K/S).
Це ПРИБЛИЗНА модель за екранним кольором фарби (hex), без спектрів пігментів. Реальний результат залежить від
пігментів, маси білого й вологості плівки: рецепти треба перевіряти пробними замісами й, за потреби, коригувати
«силу» фарби (поле strength у каталозі: 1 = середня; >1 сильніше фарбує суміш).

Рецепт = цілі частки (parts) з P (за замовчуванням 12), до max_components фарб. Перебираються ВСІ рецепти
(детерміновано); вибір за ΔE2000 з невеликим штрафом за кожен додатковий компонент."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
from skimage.color import lab2rgb, rgb2lab

from .catalog import ciede2000

COMPONENT_PENALTY = 0.4          # ΔE2000-еквівалент штрафу за кожну додаткову фарбу (простіші рецепти)
MAX_BASES = 40                   # понад це база проріджується (інакше перебір трійок завеликий)
MIN_STRENGTH, MAX_STRENGTH = 0.1, 10.0
_EPS = 0.004

_cache: dict = {}


class MixError(ValueError):
    pass


@dataclass
class Recipe:
    parts: dict[int, int]                 # індекс фарби бази -> частки
    total_parts: int
    lab: np.ndarray                       # прогнозований колір
    delta_e2000: float
    components: list[dict] = field(default_factory=list)


def _lin(srgb: np.ndarray) -> np.ndarray:
    srgb = np.clip(srgb, 0.0, 1.0)
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _unlin(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)


def _ks(refl: np.ndarray) -> np.ndarray:
    r = np.clip(refl, _EPS, 1.0)
    return (1.0 - r) ** 2 / (2.0 * r)


def _refl(ks: np.ndarray) -> np.ndarray:
    return 1.0 + ks - np.sqrt(ks * ks + 2.0 * ks)


def paint_lab(paint: dict) -> np.ndarray:
    return np.asarray(paint["lab"], np.float64)


def _base_ks(base_labs: np.ndarray) -> np.ndarray:
    rgb = lab2rgb(base_labs[None].astype(np.float64))[0]                 # (m,3) sRGB 0..1
    return _ks(_lin(rgb))


def _to_lab(ks_mix: np.ndarray) -> np.ndarray:
    return rgb2lab(_unlin(_refl(ks_mix))[:, None, :]).reshape(-1, 3)


def predict_lab(base_labs: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Колір суміші. base_labs (m,3); weights (n,m) --- невід'ємні ваги (сума по рядку = 1, сила вже врахована)."""
    return _to_lab(weights @ _base_ks(base_labs))


def _compositions(total: int, n: int):
    """Усі розбиття total на n додатних цілих (впорядковані)."""
    if n == 1:
        return [(total,)]
    return [(a,) + rest for a in range(1, total - n + 2) for rest in _compositions(total - a, n - 1)]


def _thin_bases(labs: np.ndarray, limit: int) -> list[int]:
    """Детерміноване проріджування: найдальша точка в Lab, починаючи з найсвітлішої й найтемнішої."""
    chosen = [int(np.argmax(labs[:, 0])), int(np.argmin(labs[:, 0]))]
    d = np.minimum(np.linalg.norm(labs - labs[chosen[0]], axis=1), np.linalg.norm(labs - labs[chosen[1]], axis=1))
    while len(chosen) < limit:
        j = int(np.argmax(d))
        chosen.append(j)
        d = np.minimum(d, np.linalg.norm(labs - labs[j], axis=1))
    return sorted(set(chosen))


def _table(base_labs: np.ndarray, strengths: np.ndarray, total: int, max_comp: int):
    key = (base_labs.tobytes(), strengths.tobytes(), total, max_comp)
    if key in _cache:
        return _cache[key]
    m = len(base_labs)
    idx_blocks, parts_blocks = [], []
    for n in range(1, min(max_comp, m) + 1):
        combos = np.array(list(itertools.combinations(range(m), n)), np.int16)          # (C,n)
        comps = np.array(_compositions(total, n), np.int16)                              # (c,n)
        ii = np.repeat(combos, len(comps), axis=0)
        pp = np.tile(comps, (len(combos), 1))
        pad = max_comp - n
        idx_blocks.append(np.pad(ii, ((0, 0), (0, pad)), constant_values=-1))
        parts_blocks.append(np.pad(pp, ((0, 0), (0, pad))))
    idx = np.concatenate(idx_blocks)
    parts = np.concatenate(parts_blocks)
    n_comp = (idx >= 0).sum(1)
    ks = _base_ks(base_labs)
    num = np.zeros((len(idx), 3))
    den = np.zeros(len(idx))
    for j in range(idx.shape[1]):
        ok = idx[:, j] >= 0
        w = np.where(ok, parts[:, j] * strengths[np.where(ok, idx[:, j], 0)], 0.0)
        num += w[:, None] * ks[np.where(ok, idx[:, j], 0)]
        den += w
    labs = _to_lab(num / den[:, None])
    res = (idx, parts, n_comp, labs.astype(np.float32))
    if len(_cache) > 2:
        _cache.clear()
    _cache[key] = res
    return res


def solve_mixes(targets_lab: np.ndarray, bases: list[dict], total_parts: int = 12, max_components: int = 3,
                container_ml: float = 3.0) -> tuple[list[Recipe], dict]:
    """Для кожного цільового кольору (k,3) знаходить рецепт із bases (елементи каталогу: code, name, lab, pigments, strength)."""
    if not bases:
        raise MixError("Немає базових фарб для змішування.")
    if not 2 <= total_parts <= 48:
        raise MixError("Кількість часток має бути 2..48.")
    if not 1 <= max_components <= 4:
        raise MixError("Кількість компонентів має бути 1..4.")
    labs_all = np.array([paint_lab(b) for b in bases], np.float64)
    keep = list(range(len(bases)))
    info = {"bases": len(bases), "bases_used_in_search": len(bases), "thinned": False}
    if len(bases) > MAX_BASES and max_components >= 3:
        keep = _thin_bases(labs_all, MAX_BASES)
        info.update(bases_used_in_search=len(keep), thinned=True)
    labs = labs_all[keep]
    st = np.array([min(MAX_STRENGTH, max(MIN_STRENGTH, float(bases[i].get("strength", 1.0) or 1.0))) for i in keep])
    idx, parts, n_comp, plabs = _table(labs, st, total_parts, min(max_components, len(keep)))
    pen = COMPONENT_PENALTY * (n_comp - 1).astype(np.float32)
    out: list[Recipe] = []
    for t in np.asarray(targets_lab, np.float64):
        cheap = np.linalg.norm(plabs - t.astype(np.float32), axis=1)           # ΔE76: відбір кандидатів
        cand = np.argpartition(cheap, min(64, len(cheap) - 1))[:64]
        de = ciede2000(plabs[cand].astype(np.float64), t[None, :])
        j = int(cand[int(np.argmin(de + pen[cand]))])
        used = {int(keep[idx[j, c]]): int(parts[j, c]) for c in range(idx.shape[1]) if idx[j, c] >= 0}
        comps = []
        for bi, p in sorted(used.items(), key=lambda kv: (-kv[1], kv[0])):
            ml = container_ml * p / total_parts
            comps.append({"code": bases[bi]["code"], "name": bases[bi].get("name", ""), "parts": p,
                          "ml_per_container": round(ml, 3), "pigments": list(bases[bi].get("pigments") or []),
                          "hex": bases[bi].get("hex"), "lab": [round(float(v), 2) for v in bases[bi]["lab"]]})
        out.append(Recipe(used, total_parts, plabs[j].astype(np.float64),
                          float(ciede2000(plabs[j].astype(np.float64), t)), comps))
    return out, info


def recipe_text(r: Recipe) -> str:
    def f(v):
        return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return " + ".join(f"{c['name'] or c['code']} {f(c['ml_per_container'])}" for c in r.components) + " мл"
