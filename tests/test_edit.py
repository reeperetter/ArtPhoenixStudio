import cv2
import numpy as np
import pytest

from paint_by_numbers.edit import (EditError, Segmentation, add_color, merge_into, paint_polygon, rebuild_result, smooth_region,
                                   recolor_region)
from paint_by_numbers.export.package import build_package
from paint_by_numbers.generate import run_pipeline
from paint_by_numbers.project import open_project
from paint_by_numbers.settings import Settings


def _seg():
    labels = np.zeros((20, 30), np.int32)       # три вертикальні смуги: ділянки 0, 1, 2 і кольори 0, 1, 2
    labels[:, 10:20] = 1
    labels[:, 20:] = 2
    pal = np.array([[30, 0, 0], [60, 10, 10], [90, -10, 5]], np.float32)
    return Segmentation(labels, np.array([0, 1, 2], np.int32), pal, 3, 0)


def test_recolor_merges_same_color_neighbours():
    s = recolor_region(_seg(), 0, 1)
    assert len(s.region_color) == 2 and len(s.palette_lab) == 2      # невикористаний колір прибрано з палітри
    assert (s.labels[:, :20] == s.labels[0, 0]).all()


def test_merge_requires_adjacency_and_other_region():
    s = _seg()
    with pytest.raises(EditError):
        merge_into(s, 0, 2)
    with pytest.raises(EditError):
        merge_into(s, 1, 1)
    m = merge_into(s, 1, 2)
    assert len(m.region_color) == 2 and (m.labels[:, 10:] == m.labels[0, 10]).all()


def test_paint_polygon_splits_region():
    s = paint_polygon(_seg(), [(2, 2), (7, 2), (7, 8), (2, 8)], 2)
    assert len(s.region_color) == 4 and s.region_at(4, 4) != s.region_at(1, 15)
    assert s.palette_lab[s.region_color[s.region_at(4, 4)]].tolist() == [90, -10, 5]
    with pytest.raises(EditError):
        paint_polygon(_seg(), [(0, 0), (1, 1)], 1)
    with pytest.raises(EditError):
        paint_polygon(_seg(), [(2, 2), (5, 2), (5, 5)], 0)
    with pytest.raises(EditError):
        paint_polygon(_seg(), [(100, 100), (120, 100), (120, 120)], 1)


def test_add_color_and_originals_untouched():
    s = _seg()
    s2, i = add_color(s, [50, 20, 20])
    assert i == 3 and len(s.palette_lab) == 3 and len(s2.palette_lab) == 4
    assert add_color(s2, [50, 20, 20])[1] == 3
    recolor_region(s2, 0, 3)
    assert (s2.labels == s.labels).all()


def _photo(tmp_path):
    rng = np.random.default_rng(1)
    img = np.full((200, 280, 3), (190, 170, 150), np.uint8)
    cv2.circle(img, (140, 100), 60, (60, 90, 210), -1)
    img = np.clip(img.astype(int) + rng.integers(-8, 8, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(tmp_path / "t.png"), img)
    return tmp_path / "t.png"


def test_rebuild_and_roundtrip(tmp_path):
    photo = _photo(tmp_path)
    res = run_pipeline(photo, Settings(width_mm=100.0, n_colors=6, order_number="e"))
    res.source_photo, res.original_name = photo, "t.png"
    seg = Segmentation.from_result(res)
    big = int(np.argmax(res.rm.area_px))
    seg2 = merge_into(seg, big, sorted(seg.neighbors(big))[0])
    res2 = rebuild_result(seg2, res)
    assert res2.report["manual_edits"] == 1 and len(res2.rm.palette_lab) < len(res.rm.palette_lab)
    assert res2.report["regions_without_number_room"] == 0
    info = build_package(res2, tmp_path / "out", photo, force=True, original_name="t.png")
    res3 = open_project(info["dir"])
    assert (res3.rm.labels == res2.rm.labels).all()


def _jagged():
    labels = np.zeros((60, 60), np.int32)
    labels[:, 30:] = 1
    labels[10:50:4, 28:32] = 1                  # зубці на межі
    labels[20, 10] = 1                          # вкраплення
    from paint_by_numbers.pipeline.regions import connected_regions
    L, col = connected_regions(labels, 2)
    pal = np.array([[40, 0, 0], [80, 10, 10]], np.float32)
    return Segmentation(L.astype(np.int32), col.astype(np.int32), pal, 2, 0)


def test_smooth_removes_spikes_and_is_deterministic():
    s = _jagged()
    big = int(s.labels[0, 0])                   # ліва ділянка: у ній і вкраплення, і зубці
    a = smooth_region(s, big, 4)
    b = smooth_region(s, big, 4)
    assert (a.labels == b.labels).all() and len(a.region_color) < len(s.region_color)   # вкраплення й зубці зникли
    assert len(a.palette_lab) == 2                                                    # нових кольорів немає
    assert a.labels.shape == s.labels.shape


def test_smooth_errors():
    s = _jagged()
    with pytest.raises(EditError):
        smooth_region(s, 999, 3)
    with pytest.raises(EditError):
        smooth_region(s, 0, 0)
    flat = _seg()
    with pytest.raises(EditError):
        smooth_region(flat, 0, 2)               # смуги вже гладкі
