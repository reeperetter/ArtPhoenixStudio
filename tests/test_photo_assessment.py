import cv2
import numpy as np

from paint_by_numbers.quality.photo_assessment import assess_photo


def _photo():
    import skimage.data as d
    return np.ascontiguousarray(d.astronaut()[..., ::-1])


def _codes(img):
    return {w["code"] for w in assess_photo(img, (300, 400))[1]}


def test_good_photo_has_no_quality_warnings():
    m, w = assess_photo(_photo(), (300, 400))
    assert not [x for x in w if x["code"] in ("IMG_BLUR", "IMG_DARK", "IMG_BRIGHT", "IMG_NOISY", "IMG_LOW_CONTRAST")]
    assert 0 <= m["scene_complexity"] <= 1 and m["painting_difficulty"] in ("low", "medium", "high")


def test_blur_dark_bright_noise_contrast_detected():
    p = _photo()
    assert "IMG_BLUR" in _codes(cv2.GaussianBlur(p, (0, 0), 6))
    assert "IMG_DARK" in _codes((p * 0.2).astype(np.uint8))
    assert "IMG_BRIGHT" in _codes(np.clip(p.astype(int) * 0.4 + 170, 0, 255).astype(np.uint8))
    noisy = np.clip(p + np.random.default_rng(2).normal(0, 25, p.shape), 0, 255).astype(np.uint8)
    assert "IMG_NOISY" in _codes(noisy)
    assert "IMG_LOW_CONTRAST" in _codes(((p.astype(float) - 128) * 0.2 + 128).astype(np.uint8))


def test_assessment_is_deterministic_and_in_report(tmp_path):
    from paint_by_numbers.generate import run_pipeline
    from paint_by_numbers.settings import Settings
    f = tmp_path / "p.png"
    cv2.imwrite(str(f), _photo())
    s = Settings(n_colors=6, width_mm=100.0)
    a, b = run_pipeline(f, s), run_pipeline(f, s)
    assert a.report["photo_assessment"] == b.report["photo_assessment"]
    assert "sharpness" in a.report["photo_assessment"] and "est_regions_per_100cm2" in a.report["photo_assessment"]
