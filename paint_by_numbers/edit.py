"""Ручне редагування розбиття на ділянки (без Qt, щоб це можна було перевіряти тестами).

Усі правки зводяться до зміни кольору: ділянка отримує інший колір палітри (у тому числі колір сусідньої
ділянки --- це і є злиття) або полігон зафарбовується кольором (так ділянку можна розділити чи виправити контур).
Після правки ділянки перераховуються як зв'язні компоненти кольорової карти, тому сусідні ділянки одного кольору
зливаються самі, а неприпустимих станів не виникає. Кожна правка повертає новий обʼєкт: історія (Ctrl+Z) --- просто стек
знімків. Геометрію, номери, виноски й специфікацію після правки відновлює конвеєр у режимі відкриття проєкту."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .pipeline.regions import connected_regions


class EditError(ValueError):
    """Правка неможлива (повідомлення зрозуміле оператору)."""


@dataclass(frozen=True)
class Segmentation:
    labels: np.ndarray          # HxW int32, номер ділянки
    region_color: np.ndarray    # R, індекс кольору палітри кожної ділянки
    palette_lab: np.ndarray     # K x 3, колір палітри ДО підбору фарб каталогу (для каталогу це кольори складу)
    n_before: int = 0
    merged_for_numbers: int = 0

    @classmethod
    def from_result(cls, res) -> "Segmentation":
        pal = res.palette_lab_raw if res.palette_lab_raw is not None else res.rm.palette_lab
        return cls(res.rm.labels.copy(), res.rm.color.copy(), np.asarray(pal, np.float32).copy(),
                   int(res.rm.n_before), int(res.report.get("regions_merged_for_numbers", 0)))

    @property
    def shape(self):
        return self.labels.shape

    def color_map(self) -> np.ndarray:
        return self.region_color[self.labels]

    def region_at(self, x: float, y: float) -> int:
        h, w = self.labels.shape
        xi, yi = int(x), int(y)
        if not (0 <= xi < w and 0 <= yi < h):
            raise EditError("Точка за межами полотна.")
        return int(self.labels[yi, xi])

    def colors_in_use(self) -> list[int]:
        return sorted(set(int(c) for c in np.unique(self.region_color)))

    def neighbors(self, r: int) -> set[int]:
        """Ділянки зі спільною межею (4-звʼязність)."""
        m = self.labels == r
        if not m.any():
            raise EditError(f"Ділянки {r} немає.")
        grown = cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))).astype(bool)
        return {int(v) for v in np.unique(self.labels[grown & ~m])}


def _rebuild(cmap: np.ndarray, palette: np.ndarray, old: Segmentation) -> Segmentation:
    L, col = connected_regions(cmap, len(palette))
    used = np.unique(col)
    area = np.bincount(L.ravel(), minlength=len(col))
    pal_area = np.array([area[col == c].sum() for c in used])
    order = used[np.argsort(-pal_area, kind="stable")]       # нумерація кольорів від найбільшої площі, як у конвеєрі
    remap = -np.ones(len(palette), np.int64)
    remap[order] = np.arange(len(order))
    return Segmentation(L.astype(np.int32), remap[col].astype(np.int32), np.asarray(palette, np.float32)[order],
                        old.n_before, old.merged_for_numbers)


def recolor_region(seg: Segmentation, region: int, color: int) -> Segmentation:
    if not 0 <= color < len(seg.palette_lab):
        raise EditError("Невідомий колір.")
    if not 0 <= region < len(seg.region_color):
        raise EditError("Невідома ділянка.")
    if int(seg.region_color[region]) == color:
        raise EditError("Ділянка вже має цей колір.")
    rc = seg.region_color.copy()
    rc[region] = color
    return _rebuild(rc[seg.labels], seg.palette_lab, seg)


def recolor_color(seg: Segmentation, color: int, to: int) -> Segmentation:
    """Редагування палітри готового малюнка: УСІ ділянки кольору `color` отримують колір `to`.
    Колір, що лишився без ділянок, зникає з палітри (нумерація кольорів перераховується); якщо `to` ---
    колір зі складу, якого ще не було, його спершу додають через add_color."""
    n = len(seg.palette_lab)
    if not (0 <= color < n and 0 <= to < n):
        raise EditError("Невідомий колір.")
    if color == to:
        raise EditError("Оберіть інший колір: поточний збігається з вибраним.")
    if not (seg.region_color == color).any():
        raise EditError("Цей колір не використовується в малюнку.")
    rc = seg.region_color.copy()
    rc[rc == color] = to
    return _rebuild(rc[seg.labels], seg.palette_lab, seg)


def merge_into(seg: Segmentation, region: int, into: int) -> Segmentation:
    """Ділянка `region` отримує колір сусідньої `into` і зливається з нею."""
    if region == into:
        raise EditError("Оберіть іншу ділянку.")
    if into not in seg.neighbors(region):
        raise EditError("Ділянки не межують: зливати можна лише сусідні.")
    return recolor_region(seg, region, int(seg.region_color[into]))


def paint_polygon(seg: Segmentation, points: list[tuple[float, float]], color: int) -> Segmentation:
    if len(points) < 3:
        raise EditError("Полігон потребує щонайменше трьох точок.")
    if not 0 <= color < len(seg.palette_lab):
        raise EditError("Невідомий колір.")
    h, w = seg.labels.shape
    mask = np.zeros((h, w), np.uint8)
    pts = np.round(np.array(points, np.float64)).astype(np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(mask, [pts], 1)
    if not mask.any():
        raise EditError("Полігон порожній або за межами полотна.")
    cmap = seg.color_map().copy()
    changed = mask.astype(bool) & (cmap != color)
    if not changed.any():
        raise EditError("У вибраній області вже цей колір.")
    cmap[changed] = color
    return _rebuild(cmap, seg.palette_lab, seg)


def smooth_region(seg: Segmentation, region: int, radius: int = 3) -> Segmentation:
    """Згладжує контур ділянки: у смузі навколо неї кожен піксель отримує колір, що переважає у вікні (2r+1)².
    Різкі зубці, перешийки й дрібні вкраплення зникають; решта картини не змінюється. Це мажоритарний фільтр, тому
    нових кольорів не зʼявляється, а результат детермінований (при рівності голосів лишається поточний колір)."""
    if not 0 <= region < len(seg.region_color):
        raise EditError("Невідома ділянка.")
    radius = int(radius)
    if not 1 <= radius <= 25:
        raise EditError("Сила згладжування --- від 1 до 25 пікселів.")
    h, w = seg.labels.shape
    m = (seg.labels == region).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    band = cv2.dilate(m, k).astype(bool)                       # ділянка + смуга навколо
    ys, xs = np.where(band)
    pad = radius + 1
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, h)
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, w)
    cmap = seg.color_map()
    sub = cmap[y0:y1, x0:x1]
    best = np.full(sub.shape, -1.0, np.float32)
    out = sub.copy()
    ksz = (2 * radius + 1, 2 * radius + 1)
    for c in np.unique(sub):                                  # голоси кожного кольору; тут c = індекс кольору
        v = cv2.boxFilter((sub == c).astype(np.float32), -1, ksz, normalize=True, borderType=cv2.BORDER_REPLICATE)
        v = v + (sub == c) * 1e-4                             # при рівності голосів лишається поточний колір
        upd = v > best
        out[upd] = c
        best[upd] = v[upd]
    res = cmap.copy()
    bsub = band[y0:y1, x0:x1]
    res[y0:y1, x0:x1] = np.where(bsub, out, sub)
    if (res == cmap).all():
        raise EditError("Контур ділянки вже гладкий: змін немає.")
    return _rebuild(res, seg.palette_lab, seg)


def add_color(seg: Segmentation, lab: list[float] | np.ndarray) -> tuple[Segmentation, int]:
    """Додає колір до палітри (якщо такого ще немає), повертає (нова сегментація, індекс)."""
    lab = np.asarray(lab, np.float32)
    d = np.abs(seg.palette_lab - lab).sum(1)
    if len(d) and d.min() < 0.01:
        return seg, int(d.argmin())
    pal = np.vstack([seg.palette_lab, lab[None]]).astype(np.float32)
    return Segmentation(seg.labels, seg.region_color, pal, seg.n_before, seg.merged_for_numbers), len(pal) - 1


def to_restored(seg: Segmentation) -> dict:
    return {"labels": seg.labels, "region_color": seg.region_color, "palette_lab": seg.palette_lab.copy(),
            "n_before": np.int64(seg.n_before), "merged_for_numbers": seg.merged_for_numbers}


def rebuild_result(seg: Segmentation, res, edits: int = 1):
    """Новий Result з відредагованим розбиттям: контури, номери, виноски, специфікація, превʼю й попередження."""
    from .generate import run_pipeline
    new = run_pipeline(res.source_photo, res.settings, restored=to_restored(seg))
    new.source_photo, new.original_name = res.source_photo, res.original_name
    new.report["photo"] = res.original_name
    new.report["manual_edits"] = int(res.report.get("manual_edits", 0)) + edits
    return new
