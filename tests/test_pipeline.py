import numpy as np
import cv2
from scipy import ndimage as ndi

from paint_by_numbers.generate import generate
from paint_by_numbers.settings import Settings


def _synthetic(path):
    rng = np.random.default_rng(1)
    img = np.zeros((400, 300, 3), np.uint8)
    img[:] = (200, 160, 120)
    cv2.circle(img, (150, 200), 90, (40, 60, 200), -1)
    cv2.rectangle(img, (20, 20), (120, 90), (60, 180, 60), -1)
    img = np.clip(img.astype(int) + rng.integers(-12, 12, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), img)


def test_deterministic_and_valid(tmp_path):
    photo = tmp_path / "p.png"
    _synthetic(photo)
    s = Settings(mode="balanced", n_colors=8, width_mm=100.0)
    a = generate(str(photo), s, tmp_path / "a")
    b = generate(str(photo), s, tmp_path / "b")
    # детермінованість (розділ 1.4 ТЗ)
    assert np.array_equal(a.rm.labels, b.rm.labels)
    L = a.rm.labels
    R = int(L.max()) + 1
    assert len(a.rm.area_px) == R
    assert a.rm.area_px.sum() == L.size          # без прогалин і накладань
    # кожна ділянка зв'язна
    for i in range(R):
        _, n = ndi.label(L == i)
        assert n == 1
    # сусідні ділянки не мають однакового кольору
    c = a.rm.color
    for x, y in ((L[:, :-1], L[:, 1:]), (L[:-1, :], L[1:, :])):
        m = x != y
        assert not np.any(c[x[m]] == c[y[m]])
    assert (a.out_dir / "preview" / "contour_preview.png").exists()
