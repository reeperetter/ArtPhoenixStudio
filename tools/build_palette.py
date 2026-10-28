"""Побудова складської палітри за даними (відтворюваний скрипт; результат --- JSON-каталог для програми).

Палітра = ЯКОРІ + кольори, дібрані за корпусом фото:
  * якорі: білий, чорний, сходинки сірого, ряд відтінків шкіри за ITA (individual typology angle,
    ITA = arctan((L*-50)/b*) * 180/pi; категорії шкіри за порогами ITA, див. arXiv:1910.13268, табл. 1);
  * решту добирає жадібний пошук із обміном: які кольори з кандидатів найбільше зменшують сумарну похибку
    (квадрат відстані в Lab) на пікселях корпусу, враховуючи вже обрані. Так у палітрі з'являються приглушені
    середні тони (землисті, сіро-блакитні, оливкові), у яких живе більшість реальних фото.
Корпус: ваші фото (--photos ПАПКА) і вбудовані у scikit-image зразки (--builtin). Кольори --- екранні (sRGB), НЕ реальні
фарби: після вибору постачальника палітру треба замінити мазками справжніх фарб.

Приклад: python tools/build_palette.py --photos /tmp/pbn_test --builtin --size 48 --out paint_by_numbers/assets/palettes/starter_48.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from sklearn.cluster import KMeans

SEED = 12345
SKIN_L = [80, 73, 66, 59, 52, 45, 38, 31]      # рівномірні сходинки світлості шкіри від найсвітлішої до найтемнішої


def srgb_to_lab(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab).reshape(-1, 3)


def lab_to_hex(lab) -> str:
    bgr = cv2.cvtColor(np.array([[lab]], np.float32), cv2.COLOR_Lab2BGR)[0, 0]
    r, g, b = (int(round(float(np.clip(v, 0, 1)) * 255)) for v in bgr[::-1])
    return f"#{r:02X}{g:02X}{b:02X}"


def skin_ramp() -> list[tuple[str, list[float]]]:
    """Ряд відтінків шкіри: рівні кроки L*; b* росте до темнішої шкіри, a* (рум'янець) ~ 8 + 0.4 b*.
    ITA кожного кроку = arctan((L*-50)/b*) (див. докстрінг), виходить від ~+60° до ~-40°."""
    out = []
    n = len(SKIN_L)
    for i, L in enumerate(SKIN_L):
        b = 14.0 + 6.0 * i / (n - 1)
        out.append((f"Шкіра {i + 1}", [float(L), 8.0 + 0.4 * b, b]))
    return out


def anchors() -> list[tuple[str, list[float]]]:
    return [("Білий", [97.0, 0.0, 0.0]), ("Чорний", [12.0, 0.0, 0.0])] + skin_ramp()


def load_corpus(photos: str | None, builtin: bool, width: int = 180) -> list[np.ndarray]:
    imgs = []
    if photos:
        for f in sorted(Path(photos).iterdir()):
            if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                im = cv2.imread(str(f))
                if im is not None:
                    imgs.append(im)
    if builtin:
        import skimage.data as d
        for name in ("astronaut", "chelsea", "coffee", "rocket"):
            imgs.append(np.ascontiguousarray(getattr(d, name)()[..., ::-1]))
    out = []
    for im in imgs:
        h = int(im.shape[0] * width / im.shape[1])
        out.append(srgb_to_lab(cv2.resize(im, (width, h), interpolation=cv2.INTER_AREA)))
    return out


def pooled(corpus: list[np.ndarray], per_image: int = 4000):
    rng = np.random.default_rng(SEED)
    pts, w = [], []
    for lab in corpus:
        idx = rng.choice(len(lab), min(per_image, len(lab)), replace=False)
        pts.append(lab[idx])
        w.append(np.full(len(idx), 1.0 / len(idx)))            # кожне фото має однакову вагу
    return np.vstack(pts), np.concatenate(w)


def select(points, weights, candidates, fixed, k, passes=6):
    """Обирає k кандидатів, що мінімізують зважену суму min d^2 до {fixed + обрані}."""
    D = ((points[:, None, :] - candidates[None]) ** 2).sum(2)
    base = ((points[:, None, :] - fixed[None]) ** 2).sum(2).min(1) if len(fixed) else np.full(len(points), np.inf)
    chosen, cur = [], base.copy()
    for _ in range(k):
        cost = (weights[:, None] * np.minimum(cur[:, None], D)).sum(0)
        cost[chosen] = np.inf
        j = int(np.argmin(cost))
        chosen.append(j)
        cur = np.minimum(cur, D[:, j])
    for _ in range(passes):
        improved = False
        for pos in range(k):
            rest = chosen[:pos] + chosen[pos + 1:]
            b = np.minimum(base, D[:, rest].min(1)) if rest else base
            cost = (weights[:, None] * np.minimum(b[:, None], D)).sum(0)
            cost[rest] = np.inf
            j = int(np.argmin(cost))
            if j != chosen[pos] and cost[j] < cost[chosen[pos]] - 1e-12:
                chosen[pos], improved = j, True
        if not improved:
            break
    return sorted(chosen)


def name_color(lab) -> str:
    L, a, b = lab
    C = math.hypot(a, b)
    h = (math.degrees(math.atan2(b, a)) + 360) % 360
    light = ("дуже темний" if L < 22 else "темний" if L < 40 else "середній" if L < 60 else "світлий" if L < 80 else "дуже світлий")
    if C < 7:
        return f"{light} сірий" if L > 12 else "чорний"
    if C < 16 and 20 <= h < 110:
        return f"{light} {'теплий сірий' if h < 80 else 'хакі'}"
    if C < 16:
        return f"{light} {'холодний сірий' if 180 <= h < 300 else 'сіро-рожевий'}"
    hue = ("червоний" if h < 20 or h >= 350 else "помаранчевий" if h < 50 else "жовтий" if h < 80 else "оливковий" if h < 110
           else "зелений" if h < 160 else "бірюзовий" if h < 200 else "блакитний" if h < 250 else "синій" if h < 290
           else "фіолетовий" if h < 330 else "рожевий")
    if hue in ("помаранчевий", "жовтий") and L < 55:
        hue = "коричневий"
    return f"{light} {hue}"


def build(corpus, size: int, seed: int = SEED):
    pts, w = pooled(corpus)
    A = anchors()
    fixed = np.array([c for _, c in A], np.float32)
    km = KMeans(n_clusters=350, n_init=1, random_state=seed).fit(pts, sample_weight=w)
    cand = km.cluster_centers_.astype(np.float32)
    # відкидаємо кандидатів, що майже збігаються з якорями
    far = ((cand[:, None] - fixed[None]) ** 2).sum(2).min(1) > 4.0 ** 2
    cand = cand[far]
    idx = select(pts, w, cand, fixed, size - len(A))
    chosen = cand[idx]
    items = [(n, c) for n, c in A] + [(name_color(c), list(map(float, c))) for c in chosen]
    return items


def to_catalog(items, prefix: str, title: str) -> dict:
    # впорядкування: світлі до темних, за відтінком усередині нейтральних; коди ST-01…
    order = sorted(range(len(items)), key=lambda i: (-items[i][1][0]))
    paints, seen = [], {}
    for n, i in enumerate(order, 1):
        name, lab = items[i]
        seen[name] = seen.get(name, 0) + 1
        label = name if seen[name] == 1 and not name.startswith("Шкіра") else (name if name.startswith("Шкіра") else f"{name} {seen[name]}")
        paints.append({"code": f"{prefix}-{n:02d}", "name": label, "hex": lab_to_hex(lab)})
    return {"name": title, "paints": paints}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photos", default=None)
    ap.add_argument("--builtin", action="store_true")
    ap.add_argument("--size", type=int, default=48)
    ap.add_argument("--prefix", default="ST")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    corpus = load_corpus(a.photos, a.builtin)
    if not corpus:
        print("Порожній корпус: вкажіть --photos і/або --builtin", file=sys.stderr)
        return 2
    items = build(corpus, a.size)
    cat = to_catalog(items, a.prefix, f"ЧЕРНЕТКА складської палітри на {a.size} кольорів (за корпусом із {len(corpus)} фото; "
                                      "кольори екрана, НЕ реальні фарби; замінити після вибору постачальника)")
    Path(a.out).write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.out}: {len(cat['paints'])} кольорів, корпус {len(corpus)} фото")
    return 0


if __name__ == "__main__":
    sys.exit(main())
