import json
import os

import cv2
import numpy as np
import pytest
from PIL import Image

from paint_by_numbers.export.print_ready import (PrintError, PrintProfile, load_profile, plan_tiles, raster_size,
                                                 write_print_ready)
from paint_by_numbers.generate import generate


def test_profile_validation(tmp_path):
    assert PrintProfile.from_dict({}).dpi == 300
    for bad in ({"dpi": 10}, {"bleed_mm": -1}, {"raster_format": "bmp"}, {"tiles": "B5"}, {"tiles": "50x50"},
                {"nonsense": 1}, {"wrap_mm": "5"}, {"dpi": True}):
        with pytest.raises(PrintError):
            PrintProfile.from_dict(bad)
    assert PrintProfile.from_dict({"tiles": "330x480"}).sheet_size() == (330.0, 480.0)
    assert PrintProfile.from_dict({"tiles": "330х480"}).sheet_size() == (330.0, 480.0)     # українська «х»
    f = tmp_path / "p.json"
    f.write_text("{oops", encoding="utf-8")
    with pytest.raises(PrintError):
        load_profile(f)
    f.write_text(json.dumps({"dpi": 150, "tiles": "a3"}), encoding="utf-8")
    assert load_profile(f).dpi == 150


@pytest.mark.parametrize("tw,th", [(100, 100), (340, 573), (620, 800), (200, 3000)])
def test_plan_tiles_covers_with_overlap(tw, th):
    land, sw, sh, pw, ph, xs, ys = plan_tiles(tw, th, (210.0, 297.0), 8.0, 10.0)
    for total, size, pos in ((tw, pw, xs), (th, ph, ys)):
        pos = sorted(pos)
        assert pos[0] == 0 and abs(pos[-1] + size - total) < 1e-6 or len(pos) == 1
        assert all(b - a <= size - 10.0 + 1e-6 for a, b in zip(pos, pos[1:]))          # перекриття не менше заданого
    assert ys == sorted(ys, reverse=True)
    with pytest.raises(PrintError):
        plan_tiles(300, 300, (210.0, 297.0), 100.0, 10.0)


def _result(tmp_path, **kw):
    rng = np.random.default_rng(2)
    img = np.full((160, 240, 3), (180, 160, 140), np.uint8)
    cv2.circle(img, (120, 80), 45, (50, 70, 190), -1)
    img = np.clip(img.astype(int) + rng.integers(-6, 6, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(tmp_path / "t.png"), img)
    from paint_by_numbers.settings import Settings
    return generate(str(tmp_path / "t.png"), Settings(width_mm=120.0, n_colors=6, order_number="pr", **kw), tmp_path / "o")


def test_print_ready_files_and_geometry(tmp_path):
    res = _result(tmp_path)
    p = PrintProfile(bleed_mm=4, wrap_mm=10, dpi=100, tiles="A4", tile_overlap_mm=10)
    out = write_print_ready(tmp_path / "pr", res, p)
    d = tmp_path / "pr"
    assert set(out) >= {"canvas_print_ready.pdf", "canvas_print_ready_100dpi.tif", "canvas_tiles_A4.pdf", "print_profile.json"}
    # растр: розмір = (полотно + 2*(bleed+wrap)) * dpi / 25.4, dpi записано в файл
    im = Image.open(d / "canvas_print_ready_100dpi.tif")
    assert im.size == raster_size(res, p) and round(im.info["dpi"][0]) == 100 and im.mode == "L"
    a = np.asarray(im)
    assert a[:int(p.wrap_mm * 100 / 25.4)].min() == 255          # поле загортання біле
    assert a.min() < 100                                            # а контури є
    # PDF із припуском: розмір сторінки = обріз + 2*(slug+bleed), TrimBox/BleedBox задано
    pdf = (d / "canvas_print_ready.pdf").read_bytes()
    assert pdf.startswith(b"%PDF") and b"/TrimBox" in pdf and b"/BleedBox" in pdf
    page = out["canvas_print_ready.pdf"]["page_mm"]
    assert abs(page[0] - (120 + 2 * 10 + 2 * (8 + 4))) < 0.01
    # плитки: перша сторінка --- схема, далі по сторінці на аркуш
    t = out["canvas_tiles_A4.pdf"]
    assert (d / "canvas_tiles_A4.pdf").read_bytes().count(b"/Type /Page\n") + \
        (d / "canvas_tiles_A4.pdf").read_bytes().count(b"/Type /Page ") >= t["sheets"] + 1
    assert json.loads((d / "print_profile.json").read_text(encoding="utf-8"))["dpi"] == 100


def test_raster_size_limit(tmp_path):
    res = _result(tmp_path)
    with pytest.raises(PrintError):
        write_print_ready(tmp_path / "x", res, PrintProfile(dpi=1200, bleed_mm=20, wrap_mm=100))


def test_package_includes_print_ready_only_when_requested(tmp_path):
    res = _result(tmp_path)
    assert not (res.out_dir / "print" / "print_ready").exists()
    res2 = _result(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path,
                   extra={"print_profile": PrintProfile(dpi=72, raster_format="png").to_dict()})
    f = res2.out_dir / "print" / "print_ready" / "canvas_print_ready_72dpi.png"
    assert f.is_file() and (res2.out_dir / "print" / "print_ready" / "canvas_print_ready.pdf").is_file()
    meta = json.loads((res2.out_dir / "project" / "project.json").read_text(encoding="utf-8"))
    assert any(e["path"] == "print/print_ready/canvas_print_ready_72dpi.png" for e in meta["exports"])
