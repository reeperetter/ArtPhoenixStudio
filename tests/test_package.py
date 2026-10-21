import csv
import json
import re
import xml.dom.minidom

import cv2
import numpy as np
import pytest

from paint_by_numbers.export.package import build_package
from paint_by_numbers.generate import generate, run_pipeline
from paint_by_numbers.palette.specification import containers_needed
from paint_by_numbers.settings import Settings


@pytest.fixture(scope="module")
def photo(tmp_path_factory):
    d = tmp_path_factory.mktemp("ph")
    rng = np.random.default_rng(7)
    img = np.full((300, 220, 3), (200, 170, 140), np.uint8)
    cv2.circle(img, (110, 150), 70, (40, 60, 200), -1)
    cv2.rectangle(img, (15, 15), (90, 70), (60, 180, 60), -1)
    img = np.clip(img.astype(int) + rng.integers(-15, 15, img.shape), 0, 255).astype(np.uint8)
    p = d / "p.png"
    cv2.imwrite(str(p), img)
    return p


def test_containers_math():
    assert containers_needed(0.1, 100, 1.0) == 1            # мінімум одна ємність
    assert containers_needed(100, 100, 1.0) == 1            # рівно одна: не 2 через похибку float
    assert containers_needed(100.0001, 100, 1.0) == 2       # округлення вгору
    assert containers_needed(250, 100, 1.2) == 3            # 250*1.2/100 = 3.0
    assert containers_needed(250, None, 1.0) == 1           # N не задано -> 1 ємність
    assert containers_needed(250, 0, 1.0) == 1


def test_spec_areas_match_canvas_and_large_area_gets_more_containers(photo):
    s = Settings(n_colors=8, width_mm=110.0, coverage_mm2_per_container=2000.0, safety_factor=1.2)
    res = run_pipeline(photo, s)
    t = res.spec["totals"]
    assert abs(t["canvas_area_mm2"] - t["canvas_expected_mm2"]) < 0.5
    assert abs(sum(p["area_mm2"] for p in res.spec["paints"]) - t["canvas_expected_mm2"]) < 1.0
    big = max(res.spec["paints"], key=lambda p: p["area_mm2"])
    small = min(res.spec["paints"], key=lambda p: p["area_mm2"])
    assert big["containers"] > 1 >= small["containers"] - 0   # велика площа -> кілька ємностей
    assert big["containers"] == containers_needed(big["area_mm2"], 2000.0, 1.2)
    assert res.spec["calculation"]["provisional"] is True      # N не підтверджена тестами
    assert any(w["code"] == "SPEC_PROVISIONAL" for w in res.warnings)


def test_confirmed_coverage_clears_provisional(photo):
    s = Settings(n_colors=8, width_mm=110.0, coverage_mm2_per_container=2000.0, coverage_confirmed=True)
    res = run_pipeline(photo, s)
    assert res.spec["calculation"]["provisional"] is False
    assert not any(w["code"] == "SPEC_PROVISIONAL" for w in res.warnings)


def test_package_structure_files_and_pdf_size(photo, tmp_path):
    s = Settings(n_colors=8, width_mm=110.0, order_number="000007", coverage_mm2_per_container=3000.0)
    res = generate(photo, s, tmp_path)
    d = tmp_path / "order_000007"
    assert res.out_dir == d and not res.blocked
    for rel in ["source/original_photo.png", "project/project.json", "project/regions.npz",
                "preview/color_preview.png", "preview/contour_preview.png", "preview/numbered_preview.png",
                "print/canvas_outline.svg", "print/canvas_outline.pdf", "palette/palette.png",
                "palette/paint_list.csv", "production/production_specification.pdf",
                "production/production_specification.json", "quality/quality_report.json"]:
        assert (d / rel).exists(), rel
    # PDF має фізичний розмір полотна (мм -> pt)
    pdf = (d / "print/canvas_outline.pdf").read_bytes()
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)
    w_pt, h_pt = float(m.group(1)), float(m.group(2))
    assert abs(w_pt - res.width_mm / 25.4 * 72) < 0.1 and abs(h_pt - res.height_mm / 25.4 * 72) < 0.1
    xml.dom.minidom.parse(str(d / "print/canvas_outline.svg"))
    # CSV: по рядку на колір + підсумок, розділювач ';'
    rows = list(csv.reader(open(d / "palette/paint_list.csv", encoding="utf-8-sig"), delimiter=";"))
    assert len(rows) == 1 + len(res.spec["paints"]) + 1
    assert rows[-1][0] == "TOTAL" and int(rows[-1][8]) == res.spec["totals"]["containers"]
    proj = json.loads((d / "project/project.json").read_text(encoding="utf-8"))
    assert proj["project_format_version"] == 1 and proj["settings"]["seed"] == s.seed
    assert len(proj["source"]["sha256"]) == 64
    # збережені дані відтворюють розбиття на ділянки
    z = np.load(d / "project/regions.npz")
    assert np.array_equal(z["labels"], res.rm.labels)


def test_deterministic_print_files(photo, tmp_path):
    s = Settings(n_colors=8, width_mm=110.0)
    a = generate(photo, s, tmp_path / "a")
    b = generate(photo, s, tmp_path / "b")
    for rel in ["print/canvas_outline.svg", "palette/paint_list.csv", "production/production_specification.json"]:
        assert (a.out_dir / rel).read_bytes() == (b.out_dir / rel).read_bytes(), rel


def test_critical_error_blocks_production_files(photo, tmp_path):
    res = run_pipeline(photo, Settings(n_colors=8, width_mm=110.0))
    res.warnings.append({"code": "GEO_TOPOLOGY", "severity": "critical", "message": "x", "recommendation": "y"})
    info = build_package(res, tmp_path, photo)
    d = info["dir"]
    assert info["blocked"]
    assert list((d / "print").iterdir()) == [] and list((d / "production").iterdir()) == []
    assert (d / "quality/quality_report.json").exists() and (d / "project/project.json").exists()
    assert json.loads((d / "project/project.json").read_text(encoding="utf-8"))["status"] == "blocked"
    forced = build_package(res, tmp_path, photo, force=True)         # явне підтвердження оператора
    assert not forced["blocked"] and (forced["dir"] / "print/canvas_outline.pdf").exists()


def test_failed_rebuild_keeps_previous_package(photo, tmp_path):
    res = run_pipeline(photo, Settings(n_colors=8, width_mm=110.0, order_number="000009"))
    d = build_package(res, tmp_path, photo)["dir"]
    before = (d / "print/canvas_outline.svg").read_bytes()
    with pytest.raises(FileNotFoundError):
        build_package(res, tmp_path, tmp_path / "missing.png")
    assert (d / "print/canvas_outline.svg").read_bytes() == before
    assert not list(tmp_path.glob(".order_*.tmp"))                    # тимчасова папка прибрана
