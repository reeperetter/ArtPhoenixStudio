import cv2
import numpy as np

from paint_by_numbers.generate import generate
from paint_by_numbers.pipeline.preprocess import skin_map
from paint_by_numbers.settings import Settings


def _face(tmp_path):
    img = np.full((300, 400, 3), (200, 190, 170), np.uint8)
    cv2.ellipse(img, (200, 150), (90, 110), 0, 0, 360, (140, 160, 215), -1)      # колір шкіри (BGR)
    cv2.circle(img, (170, 130), 8, (40, 40, 40), -1)
    rng = np.random.default_rng(0)
    img = np.clip(img.astype(int) + rng.integers(-5, 5, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(tmp_path / "f.png"), img)
    return img


def test_skin_map_marks_face_not_background(tmp_path):
    img = _face(tmp_path)
    m = skin_map(img)
    assert m[150, 200] > 0.9 and m[10, 10] < 0.1 and m.shape == img.shape[:2]
    assert 0.0 <= m.min() and m.max() <= 1.0


def test_detail_and_auto_detail_are_deterministic_and_finer(tmp_path):
    _face(tmp_path)
    base = Settings(width_mm=100.0, n_colors=8, order_number="a")
    fine = Settings(width_mm=100.0, n_colors=8, order_number="a", detail=1.6)
    r1 = generate(str(tmp_path / "f.png"), base, tmp_path / "o1", force=True)
    r2 = generate(str(tmp_path / "f.png"), base, tmp_path / "o2", force=True)
    r3 = generate(str(tmp_path / "f.png"), fine, tmp_path / "o3", force=True)
    assert (r1.rm.labels == r2.rm.labels).all()
    assert r3.report["regions_final"] >= r1.report["regions_final"]
