import json

import cv2
import numpy as np
import pytest

from paint_by_numbers import cli
from paint_by_numbers.generate import build_zone_maps, generate, run_pipeline, zone_metrics
from paint_by_numbers.image_io.loader import load_image
from paint_by_numbers.pipeline.priority_zones import ZoneError, parse_zones, rasterize
from paint_by_numbers.settings import Settings


def test_parse_valid_shapes_and_defaults():
    z = parse_zones([
        {"shape": "rect", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.4},
        {"name": "e", "shape": "ellipse", "cx": 0.5, "cy": 0.5, "rx": 0.1, "ry": 0.2, "weight": 3, "angle": 30},
        {"shape": "polygon", "points": [[0, 0], [1, 0], [0.5, 1]], "frame": "photo"},
    ])
    assert [q.shape for q in z] == ["rect", "ellipse", "polygon"]
    assert z[0].weight == 2.0 and z[0].name == "zone1" and z[2].frame == "photo"
    assert parse_zones(None) == [] and parse_zones([]) == []


@pytest.mark.parametrize("bad", [
    {"shape": "star"},
    {"shape": "rect", "x0": 0.5, "y0": 0.1, "x1": 0.2, "y1": 0.4},        # x0 >= x1
    {"shape": "rect", "x0": -0.1, "y0": 0.1, "x1": 0.2, "y1": 0.4},       # поза 0..1
    {"shape": "rect", "x0": 0.1, "y0": 0.1, "x1": 0.2},                    # немає y1
    {"shape": "ellipse", "cx": 0.5, "cy": 0.5, "rx": 0, "ry": 0.1},
    {"shape": "polygon", "points": [[0, 0], [1, 1]]},
    {"shape": "polygon", "points": [[0, 0], [1, 1], [2, 0]]},              # координата > 1
    {"shape": "rect", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.4, "weight": 0},
    {"shape": "rect", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.4, "weight": 9},
    {"shape": "rect", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.4, "frame": "x"},
])
def test_parse_rejects_bad_zones(bad):
    with pytest.raises(ZoneError):
        parse_zones([bad])


def test_rasterize_core_feather_and_outside():
    W, H = 200, 100
    z = parse_zones([{"shape": "ellipse", "cx": 0.5, "cy": 0.5, "rx": 0.2, "ry": 0.3, "weight": 3}])
    m = rasterize(z, W, H, px_per_mm=2.0, crop=(0, 0, W, H), src_size=(W, H), feather_mm=5.0)   # край 10 px
    assert m.weight[50, 100] == 3.0                         # центр: повна вага
    assert m.weight[50, 5] == 0.0                           # далеко: нуль
    row = m.weight[50, 100 + 40:100 + 60]                   # праворуч від краю еліпса (rx=40 px)
    assert np.all(np.diff(row) <= 1e-6)                     # вага спадає назовні
    assert 0 < row[3] < 3
    assert m.unit.max() == 1.0 and m.unit[50, 5] == 0.0
    assert m.zones[0].pixels > 0


def test_photo_frame_accounts_for_crop():
    # фото 200x100, полотно кадруюється до центральних 100x100: пікселі x 50..150
    z = parse_zones([{"shape": "rect", "x0": 0.25, "y0": 0.0, "x1": 0.75, "y1": 1.0, "frame": "photo"}])
    m = rasterize(z, 100, 100, 1.0, crop=(50, 0, 150, 100), src_size=(200, 100), feather_mm=0.0001)
    assert m.zones[0].inside[:, 2:98].all()                  # покриває все полотно
    z2 = parse_zones([{"shape": "rect", "x0": 0.0, "y0": 0.0, "x1": 0.2, "y1": 1.0, "frame": "photo"}])
    m2 = rasterize(z2, 100, 100, 1.0, crop=(50, 0, 150, 100), src_size=(200, 100), feather_mm=0.0001)
    assert m2.zones[0].pixels == 0                           # цілком у відрізаній частині


@pytest.fixture(scope="module")
def detail_photo(tmp_path_factory):
    """Плавний фон і дрібні деталі («очі», «рот») усередині майбутньої зони."""
    rng = np.random.default_rng(5)
    h, w = 330, 240
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.float32)
    img[..., 0] = 150 + 40 * xx / w
    img[..., 1] = 160 + 30 * yy / h
    img[..., 2] = 175
    for cx in (85, 150):
        cv2.circle(img, (cx, 110), 7, (30, 30, 40), -1)
        cv2.circle(img, (cx, 110), 3, (240, 240, 240), -1)
    cv2.ellipse(img, (118, 170), (30, 6), 0, 0, 180, (60, 60, 160), 3)
    img = np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)
    p = tmp_path_factory.mktemp("d") / "d.png"
    cv2.imwrite(str(p), img)
    return p


ZONE = [{"name": "face", "shape": "rect", "x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.65, "weight": 3}]


def test_zone_improves_fidelity_inside_and_keeps_topology(detail_photo, tmp_path):
    base = Settings(n_colors=8, width_mm=80.0)
    zoned = Settings(n_colors=8, width_mm=80.0, zones=ZONE)
    rb = run_pipeline(detail_photo, base)
    rz = run_pipeline(detail_photo, zoned)
    img = load_image(str(detail_photo), 80.0, None, 3.0)
    zm = build_zone_maps(zoned, img)
    mb = zone_metrics(zm, rb.rm, rb.spots, img.bgr, rb.color_img, 3.0)["zones"][0]
    mz = zone_metrics(zm, rz.rm, rz.spots, img.bgr, rz.color_img, 3.0)["zones"][0]
    assert mz["delta_e76"] <= mb["delta_e76"] + 0.05          # у зоні похибка не гірша
    assert rz.geom.topology["ok"] and rb.geom.topology["ok"]
    assert rz.report["priority_zones"]["zones"][0]["name"] == "face"
    assert not any(w["code"] == "PRIORITY_ZONES_NOT_SET" for w in rz.warnings)
    assert any(w["code"] == "PRIORITY_ZONES_NOT_SET" for w in rb.warnings)


def test_zoned_package_deterministic_and_saved(detail_photo, tmp_path):
    s = Settings(n_colors=8, width_mm=80.0, zones=ZONE)
    a = generate(detail_photo, s, tmp_path / "a")
    b = generate(detail_photo, s, tmp_path / "b")
    assert (a.out_dir / "quality/zones_preview.png").exists()
    assert (a.out_dir / "print/canvas_outline.svg").read_bytes() == (b.out_dir / "print/canvas_outline.svg").read_bytes()
    proj = json.loads((a.out_dir / "project/project.json").read_text(encoding="utf-8"))
    assert proj["settings"]["zones"][0]["name"] == "face"       # зони зберігаються в проєкті


def test_zone_outside_canvas_warns(detail_photo):
    # фото 240x330 кадрується до квадрата; зона на самому верху фото відрізається
    z = [{"name": "top", "shape": "rect", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.05, "frame": "photo"}]
    res = run_pipeline(detail_photo, Settings(n_colors=8, width_mm=80.0, height_mm=80.0, zones=z))
    assert any(w["code"] == "ZONE_EMPTY" for w in res.warnings)


def test_cli_reports_bad_zone_file(detail_photo, tmp_path, capsys):
    bad = tmp_path / "z.json"
    bad.write_text(json.dumps({"zones": [{"shape": "rect", "x0": 0.9, "y0": 0, "x1": 0.1, "y1": 1}]}))
    rc = cli.main([str(detail_photo), "-o", str(tmp_path / "o"), "--zones", str(bad)])
    assert rc == 2 and "зонах пріоритету" in capsys.readouterr().err
    notjson = tmp_path / "n.json"
    notjson.write_text("{oops")
    assert cli.main([str(detail_photo), "-o", str(tmp_path / "o"), "--zones", str(notjson)]) == 2
