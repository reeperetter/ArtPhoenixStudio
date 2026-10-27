import cv2
import numpy as np

from paint_by_numbers.export.client_preview import before_after_png, detail_window
from paint_by_numbers.generate import generate, run_pipeline
from paint_by_numbers.settings import Settings


def _photo(tmp_path):
    rng = np.random.default_rng(1)
    img = np.full((240, 320, 3), (190, 170, 150), np.uint8)
    cv2.circle(img, (160, 120), 70, (60, 90, 210), -1)
    img = np.clip(img.astype(int) + rng.integers(-8, 8, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(tmp_path / "t.png"), img)
    return tmp_path / "t.png"


def test_package_has_client_preview(tmp_path):
    photo = _photo(tmp_path)
    res = generate(str(photo), Settings(width_mm=200.0, n_colors=8, order_number="cp", project_name="Тест",
                                        extra={"store_name": "Магазин іграшок"}), tmp_path / "o")
    pdf = res.out_dir / "preview" / "client_preview.pdf"
    png = res.out_dir / "preview" / "client_before_after.png"
    assert pdf.read_bytes()[:4] == b"%PDF" and pdf.stat().st_size > 5000
    img = cv2.imread(str(png))
    assert img is not None and img.shape[1] > img.shape[0] * 0.8        # фото й картина поруч
    assert b"/Count 1" in pdf.read_bytes()                                # рівно одна сторінка


def test_detail_window_inside_canvas_and_follows_zone(tmp_path):
    photo = _photo(tmp_path)
    res = run_pipeline(photo, Settings(width_mm=200.0, n_colors=8))
    h, w = res.rm.labels.shape
    x0, y0, x1, y1 = detail_window(res)
    assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
    z = {"name": "z", "shape": "ellipse", "cx": 0.2, "cy": 0.2, "rx": 0.1, "ry": 0.1, "weight": 2}
    res2 = run_pipeline(photo, Settings(width_mm=200.0, n_colors=8, zones=[z]))
    a, b, c, d = detail_window(res2)
    assert a < (w - (c - a)) / 2 and b < (h - (d - b)) / 2             # вікно зсунулося до зони зліва вгорі


def test_before_after_png_shape():
    a = np.zeros((100, 60, 3), np.uint8)
    b = np.full((120, 72, 3), 255, np.uint8)
    out = before_after_png(a, b)
    assert out.shape[0] == 120 and out.shape[1] > 120
