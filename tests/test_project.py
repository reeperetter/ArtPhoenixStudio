import json
import shutil
import time

import cv2
import numpy as np
import pytest

from paint_by_numbers.export.package import build_package
from paint_by_numbers.generate import generate
from paint_by_numbers.project import ProjectError, open_project
from paint_by_numbers.settings import Settings


def _photo(path):
    rng = np.random.default_rng(5)
    img = np.full((300, 400, 3), (200, 160, 120), np.uint8)
    cv2.circle(img, (200, 150), 80, (40, 60, 200), -1)
    cv2.rectangle(img, (20, 20), (120, 90), (60, 180, 60), -1)
    img = np.clip(img.astype(int) + rng.integers(-12, 12, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), img)


def _cat():
    return [{"code": f"C{i}", "name": f"n{i}", "hex": h, "lab": None} for i, h in enumerate(
        ["#C8A078", "#2846C8", "#3CB43C", "#FFFFFF", "#000000", "#808080", "#E0C0A0", "#204080", "#80C080", "#A04040"])]


@pytest.fixture
def project(tmp_path):
    from paint_by_numbers.palette.catalog import parse_catalog
    photo = tmp_path / "p.png"
    _photo(photo)
    cat = parse_catalog([{"code": c["code"], "name": c["name"], "hex": c["hex"]} for c in _cat()])[1]
    s = Settings(mode="balanced", n_colors=8, width_mm=120.0, order_number="r1", project_name="тест",
                 coverage_mm2_per_container=9000.0, safety_factor=1.2, catalog=cat, zones=[
                     {"name": "центр", "shape": "ellipse", "cx": 0.5, "cy": 0.5, "rx": 0.2, "ry": 0.25, "weight": 2.5}])
    res = generate(str(photo), s, tmp_path / "out")
    return tmp_path, res


def test_reopen_matches_original(project):
    tmp_path, a = project
    t0 = time.perf_counter()
    b = open_project(tmp_path / "out" / "order_r1")
    t_open = time.perf_counter() - t0
    assert np.array_equal(a.rm.labels, b.rm.labels) and np.array_equal(a.rm.color, b.rm.color)
    assert np.allclose(a.rm.palette_lab, b.rm.palette_lab)
    assert len(a.geom.chains) == len(b.geom.chains)
    assert all(np.allclose(x.pts, y.pts) for x, y in zip(a.geom.chains, b.geom.chains))
    key = lambda r: [(s.region, s.number, round(s.x, 3), round(s.y, 3), round(s.digit_px, 3), s.anchor) for s in r.spots]
    assert key(a) == key(b)
    assert a.spec["totals"] == b.spec["totals"] and a.spec["paints"] == b.spec["paints"]
    assert np.array_equal(a.numbered_img, b.numbered_img)
    for k in ("regions_final", "regions_before_merge", "regions_merged_for_numbers", "regions_with_leader",
              "mean_delta_e76", "ssim_gray", "spec_totals", "priority_zones", "catalog"):
        assert a.report[k] == b.report[k], k
    assert b.settings.zones == a.settings.zones and b.settings.project_name == "тест"
    assert b.report["restored_from_project"] and b.report["photo"] == "p.png"
    assert "quantize" not in b.report["timings_s"] and "merge" not in b.report["timings_s"]
    # повторне збереження пакета з відкритого проєкту дає ті самі виробничі файли
    info = build_package(b, tmp_path / "out2", b.source_photo, original_name=b.original_name)
    assert (tmp_path / "out2" / "order_r1" / "print" / "canvas_outline.svg").read_text() == \
        (tmp_path / "out" / "order_r1" / "print" / "canvas_outline.svg").read_text()
    meta = json.loads((tmp_path / "out2" / "order_r1" / "project" / "project.json").read_text(encoding="utf-8"))
    assert meta["source"]["original_name"] == "p.png" and not info["blocked"]
    c = open_project(tmp_path / "out2" / "order_r1" / "project" / "project.json")      # можна вказати й project.json
    assert np.array_equal(c.rm.labels, a.rm.labels)


def test_reopen_errors(project):
    tmp_path, _ = project
    d = tmp_path / "out" / "order_r1"
    with pytest.raises(ProjectError, match="project.json"):
        open_project(tmp_path)
    bad = tmp_path / "bad"
    shutil.copytree(d, bad)
    (bad / "project" / "project.json").write_text("{не json", encoding="utf-8")
    with pytest.raises(ProjectError, match="пошкоджено"):
        open_project(bad)
    m = json.loads((d / "project" / "project.json").read_text(encoding="utf-8"))
    for mutate, msg in ((lambda x: x.update(project_format_version=99), "версія"),
                        (lambda x: x.pop("settings"), "бракує")):
        cp = tmp_path / f"cp{msg}"
        shutil.copytree(d, cp)
        mm = json.loads(json.dumps(m))
        mutate(mm)
        (cp / "project" / "project.json").write_text(json.dumps(mm), encoding="utf-8")
        with pytest.raises(ProjectError, match=msg):
            open_project(cp)
    nosrc = tmp_path / "nosrc"
    shutil.copytree(d, nosrc)
    shutil.rmtree(nosrc / "source")
    with pytest.raises(ProjectError, match="оригіналу"):
        open_project(nosrc)
    wrong = tmp_path / "wrong"
    shutil.copytree(d, wrong)
    z = dict(np.load(wrong / "project" / "regions.npz"))
    z["labels"] = z["labels"][:-3]
    np.savez_compressed(wrong / "project" / "regions.npz", **z)
    with pytest.raises(ProjectError, match="не збігається"):
        open_project(wrong)
    z = dict(np.load(d / "project" / "regions.npz"))
    z["labels"] = z["labels"] + 10_000
    np.savez_compressed(wrong / "project" / "regions.npz", **z)
    with pytest.raises(ProjectError):
        open_project(wrong)


def test_cli_open_project(project, capsys):
    from paint_by_numbers.cli import main
    tmp_path, a = project
    d = str(tmp_path / "out" / "order_r1")
    assert main(["--open-project", d]) == 0
    assert "Проєкт відкрито" in capsys.readouterr().out
    assert main(["--open-project", d, "-o", str(tmp_path / "re")]) == 0
    assert (tmp_path / "re" / "order_r1" / "production" / "production_specification.pdf").exists()
    assert main(["--open-project", str(tmp_path)]) == 2
