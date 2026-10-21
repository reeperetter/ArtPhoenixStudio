import cv2
import numpy as np
import pytest

from paint_by_numbers.compare import (contact_sheet, default_variants, generate_best, pick_best, score_of)
from paint_by_numbers.settings import Settings


def _row(mode, colors, **kw):
    r = dict(mode=mode, colors_requested=colors, regions=300, regions_no_number=0, regions_leader=10,
             regions_narrow=5, regions_small=5, regions_per_100cm2=25.0, delta_e76_weighted=8.0, ssim=0.7, critical=0)
    r.update(kw)
    r.update(score_of(r))
    return r


def test_default_variants_clamped_and_deduped():
    v = default_variants(Settings())
    assert ("simple", 8) in v and ("balanced", 24) in v and ("detailed", 44) in v and len(v) == 9
    assert default_variants(Settings(), ["balanced"], [70, 70, 2]) == [("balanced", 64), ("balanced", 4)]
    with pytest.raises(ValueError):
        default_variants(Settings(), ["nope"])


def test_score_monotonic():
    good, worse_color, unplaced = _row("balanced", 24), _row("balanced", 24, delta_e76_weighted=16.0), \
        _row("balanced", 24, regions_no_number=30)
    assert good["score"] > worse_color["score"] and good["score"] > unplaced["score"]
    assert 0.0 <= good["score"] <= 1.0


def test_pick_best_rules():
    rows = [_row("detailed", 36, ssim=0.9, critical=1),          # найкращий за якістю, але заблокований
            _row("balanced", 24), _row("simple", 16), _row("balanced", 16)]
    assert pick_best(rows) == 2          # рівна оцінка: менше кольорів, далі простіший режим (simple 16 < balanced 16)
    assert pick_best(rows[:2]) == 1
    assert pick_best([_row("simple", 16, critical=1)]) is None
    assert pick_best([{"mode": "simple", "colors_requested": 8, "error": "x", "critical": 0}]) is None


def test_contact_sheet_and_end_to_end(tmp_path):
    rows = [_row("simple", 8), _row("balanced", 16, error=None)]
    rows[1].pop("error")
    sheet = contact_sheet(rows, 0)
    assert sheet.ndim == 3 and sheet.shape[1] > 300

    rng = np.random.default_rng(2)
    img = np.full((240, 320, 3), (200, 160, 120), np.uint8)
    cv2.circle(img, (160, 120), 70, (40, 60, 200), -1)
    img = np.clip(img.astype(int) + rng.integers(-10, 10, img.shape), 0, 255).astype(np.uint8)
    photo = tmp_path / "p.png"
    cv2.imwrite(str(photo), img)
    s = Settings(width_mm=100.0, order_number="cmp")
    seen = []
    res = generate_best(str(photo), s, tmp_path / "out", [("simple", 6), ("balanced", 8)], jobs=2,
                        progress=lambda i, n: seen.append((i, n)))
    assert seen[-1] == (2, 2)
    assert res.candidates["selected"] is not None and len(res.candidates["candidates"]) == 2
    d = tmp_path / "out" / "order_cmp"
    assert (d / "quality/candidates.png").exists() and (d / "quality/candidates.json").exists()
    # обраний варіант справді відповідає вибору (детермінованість повторного запуску)
    sel = res.candidates["selected"]
    best = res.candidates["candidates"][res.candidates["selected_index"]]
    assert res.settings.mode == sel["mode"] and res.report["regions_final"] == best["regions"]
