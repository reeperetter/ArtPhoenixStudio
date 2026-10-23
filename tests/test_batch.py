import csv
import json

import cv2
import numpy as np
import pytest

from paint_by_numbers.batch import (build_items, discover, exit_code, natural_key, read_manifest, run_batch,
                                    safe_order, write_report)
from paint_by_numbers.cli import main
from paint_by_numbers.settings import Settings


def _img(path, seed, size=(240, 320)):
    rng = np.random.default_rng(seed)
    img = np.full((*size, 3), (200, 160, 120), np.uint8)
    cv2.circle(img, (size[1] // 2, size[0] // 2), 60 + seed, (40, 60, 200), -1)
    img = np.clip(img.astype(int) + rng.integers(-10, 10, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), img)


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    for i, n in enumerate(["foto 10.png", "foto 2.png", "клієнт_1.jpg"]):
        _img(d / n, i)
    (d / "notes.txt").write_text("не фото")
    (d / ".hidden.png").write_bytes(b"x")
    return d


def test_helpers():
    assert safe_order("  а/б в?.jpg ") == "а_б_в_jpg" and safe_order("///") == "order"
    assert sorted(["f10", "f2", "f1"], key=natural_key) == ["f1", "f2", "f10"]


def test_discover_and_items(folder):
    files = discover(folder)
    assert [f.name for f in files] == ["foto 2.png", "foto 10.png", "клієнт_1.jpg"]   # природний порядок, без чужих файлів
    base = Settings(width_mm=100.0)
    it = build_items(folder, base)
    assert [i.order for i in it] == ["foto_2", "foto_10", "клієнт_1"] and all(i.settings for i in it)
    seq = build_items(folder, base, "sequential", 5, "A")
    assert [i.order for i in seq] == ["A000005", "A000006", "A000007"]
    # зони-«супутники» підхоплюються автоматично, а некоректні --- помилка лише цього фото
    (folder / "foto 2.zones.json").write_text(json.dumps({"zones": [
        {"name": "z", "shape": "rect", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}]}))
    (folder / "foto 10.zones.json").write_text(json.dumps({"zones": [{"shape": "circle"}]}))
    it = build_items(folder, base)
    assert it[0].settings.zones and it[1].settings is None and "зони" in it[1].error and it[2].settings


def test_manifest_overrides_and_errors(folder, tmp_path):
    m = tmp_path / "m.csv"
    with open(m, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["file", "order", "name", "width_mm", "height_mm", "mode", "colors"])
        w.writerow([str(folder / "foto 2.png"), "K-100", "Іван", "250,5", "300", "simple", "12"])
        w.writerow([str(folder / "foto 10.png"), "K-100", "", "", "", "", ""])          # дубль номера
        w.writerow([str(folder / "немає.png"), "", "", "", "", "", ""])
        w.writerow([str(folder / "клієнт_1.jpg"), "", "", "10", "", "", ""])             # розмір поза межами
        w.writerow([str(folder / "клієнт_1.jpg"), "K-3", "", "", "", "turbo", ""])       # невідомий режим
    it = build_items(m, Settings())
    s = it[0].settings
    assert (it[0].order, s.project_name, s.width_mm, s.height_mm, s.mode, s.n_colors) == ("K-100", "Іван", 250.5, 300.0, "simple", 12)
    assert "уже використано" in it[1].error and "не знайдено" in it[2].error
    assert "поза межами" in it[3].error and "невідомий режим" in it[4].error
    with pytest.raises(ValueError):
        (tmp_path / "bad.csv").write_text("a;b\n1;2\n")
        read_manifest(tmp_path / "bad.csv")


def test_run_batch_parallel_skip_and_report(folder, tmp_path):
    out = tmp_path / "out"
    base = Settings(width_mm=100.0, n_colors=6)
    items = build_items(folder, base)
    (folder / "foto 10.zones.json").write_text("{не json")
    items = build_items(folder, base)
    seen = []
    rows = run_batch(items, out, jobs=2, progress=lambda d, t, r: seen.append((d, t, r["status"])))
    assert [r["status"] for r in rows] == ["ok", "error", "ok"] and seen[-1][:2] == (3, 3)
    assert (out / "order_foto_2" / "print" / "canvas_outline.svg").exists()
    assert (out / "order_клієнт_1" / "production" / "production_specification.pdf").exists()
    assert not (out / "order_foto_10").exists()
    assert rows[0]["regions"] and rows[0]["containers"] and rows[1]["message"]
    csv_path = write_report(rows, out, base)
    data = json.loads((out / "batch_report.json").read_text(encoding="utf-8"))
    assert data["counts"] == {"ok": 2, "error": 1} and csv_path.exists() and exit_code(rows) == 2
    # повторний запуск із --skip-existing не перераховує готове
    rows2 = run_batch(items, out, jobs=1, skip_existing=True)
    assert [r["status"] for r in rows2] == ["skipped", "error", "skipped"] and exit_code(rows2) == 2
    # однакові результати незалежно від кількості процесів (детермінованість)
    out2 = tmp_path / "out2"
    run_batch([i for i in items if i.settings], out2, jobs=1)
    a = (out / "order_foto_2" / "print" / "canvas_outline.svg").read_text()
    b = (out2 / "order_foto_2" / "print" / "canvas_outline.svg").read_text()
    assert a == b


def test_cancel(folder, tmp_path):
    items = build_items(folder, Settings(width_mm=100.0, n_colors=6))
    calls = []
    rows = run_batch(items, tmp_path / "c", jobs=1, progress=lambda d, t, r: calls.append(d), cancel=lambda: len(calls) >= 1)
    assert [r["status"] for r in rows] == ["ok", "cancelled", "cancelled"]


def test_cli_batch(folder, tmp_path, capsys):
    out = tmp_path / "cli"
    code = main(["--batch", str(folder), "-o", str(out), "--width-mm", "100", "--colors", "6", "--jobs", "1",
                 "--order-numbering", "sequential", "--order-prefix", "S"])
    txt = capsys.readouterr().out
    assert code == 0 and "[3/3]" in txt and "Підсумок" in txt
    assert (out / "order_S000001").is_dir() and (out / "batch_report.csv").exists()
    assert main(["--batch", str(tmp_path / "порожньо")]) == 2
