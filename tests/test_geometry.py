import xml.dom.minidom

import cv2
import numpy as np
import shapely
from shapely.geometry import Point

from paint_by_numbers.export.svg import write_svg
from paint_by_numbers.generate import generate
from paint_by_numbers.geometry.labels import place_numbers_vector
from paint_by_numbers.geometry.planar import build_geometry
from paint_by_numbers.settings import Settings


def _grid_labels():
    # 4 області + острівець всередині однієї з них + область-«перемичка», що торкається діагоналлю
    L = np.zeros((60, 80), np.int32)
    L[:, 40:] = 1
    L[30:, :40] = 2
    L[30:, 40:] = 3
    L[10:20, 10:25] = 4            # острівець у області 0
    L[0:10, 30:40] = 5
    return L


def test_shared_edges_no_gaps_no_overlaps():
    L = _grid_labels()
    sal = np.zeros(L.shape, np.float32)
    g = build_geometry(L, sal)
    assert g.topology["ok"], g.topology
    assert len(g.faces) == int(L.max()) + 1
    assert abs(sum(f.area for f in g.faces.values()) - L.size) < 1e-6
    # область з острівцем має отвір
    assert len(g.faces[0].interiors) == 1
    # кожна спільна межа існує в єдиному екземплярі: немає двох ребер з однаковою парою та кінцями
    keys = set()
    for c in g.chains:
        k = (c.pair, tuple(c.raw[0]), tuple(c.raw[-1]), len(c.raw))
        assert k not in keys
        keys.add(k)


def test_nodes_are_fixed_and_border_is_straight():
    L = _grid_labels()
    g = build_geometry(L, np.zeros(L.shape, np.float32))
    assert any(c.closed for c in g.chains)           # острівець без вузлів
    for c in g.chains:
        if c.closed:                                  # замкнене ребро без вузлів: початкової точки не фіксуємо
            continue
        assert np.array_equal(c.pts[0], c.raw[0]) and np.array_equal(c.pts[-1], c.raw[-1])
        if c.pair[0] == -1:
            # межа полотна не спотворюється: усі вершини на краю
            xs, ys = c.pts[:, 0], c.pts[:, 1]
            assert np.all((xs == 0) | (xs == 80) | (ys == 0) | (ys == 60))


def test_numbers_inside_regions_and_svg_valid(tmp_path):
    L = _grid_labels()
    g = build_geometry(L, np.zeros(L.shape, np.float32))
    color = np.arange(int(L.max()) + 1) % 3
    spots = place_numbers_vector(g.faces, color, min_digit_px=2.0, max_digit_px=6.0, line_px=0.5)
    for s in spots:
        assert g.faces[s.region].contains(Point(s.x, s.y))      # номер всередині своєї ділянки
    out = tmp_path / "o.svg"
    info = write_svg(out, g, spots, px_per_mm=1.0, width_mm=80, height_mm=60, line_mm=0.2)
    xml.dom.minidom.parse(str(out))
    assert info["paths"] == len(g.chains)


def test_full_pipeline_topology_ok(tmp_path):
    rng = np.random.default_rng(3)
    img = np.full((300, 220, 3), (200, 170, 140), np.uint8)
    cv2.circle(img, (110, 150), 70, (40, 60, 200), -1)
    cv2.circle(img, (90, 130), 12, (240, 240, 240), -1)
    cv2.rectangle(img, (15, 15), (90, 70), (60, 180, 60), -1)
    img = np.clip(img.astype(int) + rng.integers(-15, 15, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(tmp_path / "p.png"), img)
    res = generate(str(tmp_path / "p.png"), Settings(n_colors=8, width_mm=110.0), tmp_path / "o")
    assert res.report["topology"]["ok"]
    assert (res.out_dir / "print" / "canvas_outline.svg").exists()
