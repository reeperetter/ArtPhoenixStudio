import numpy as np
import pytest

from paint_by_numbers.palette.catalog import CatalogError, ciede2000, match_palette, parse_catalog

# еталонні пари з Sharma, Wu, Dalal (2005), «The CIEDE2000 colour-difference formula»
SHARMA = [
    ((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
    ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615),
    ((50, -1.3802, -84.2814), (50, 0, -82.7485), 1.0000),
    ((50, 0, 0), (50, -1, 2), 2.3669),
    ((50, 2.5, 0), (50, 0, -2.5), 4.3065),
    ((50, 2.5, 0), (73, 25, -18), 27.1492),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
]


@pytest.mark.parametrize("a,b,expected", SHARMA)
def test_ciede2000_reference(a, b, expected):
    assert abs(float(ciede2000(np.array(a), np.array(b))) - expected) < 1e-3
    assert abs(float(ciede2000(np.array(b), np.array(a))) - expected) < 1e-3     # симетрія


def test_match_unique_and_nearest():
    _, cat = parse_catalog({"paints": [{"code": "A", "hex": "#FF0000"}, {"code": "B", "hex": "#0000FF"},
                                       {"code": "C", "hex": "#FFFFFF"}]})
    pal = np.array([cat[1]["lab"], cat[0]["lab"]], np.float32)
    m = match_palette(pal, cat)
    assert [x.paint["code"] for x in m] == ["B", "A"] and all(x.delta_e2000 < 1e-3 for x in m)
    # два близьких кольори не отримають одну й ту саму фарбу
    near = np.array([cat[0]["lab"], np.array(cat[0]["lab"]) + 1.0], np.float32)
    assert len({x.paint["code"] for x in match_palette(near, cat)}) == 2
    # каталог менший за палітру -> дублювання з прапорцем
    many = np.array([cat[0]["lab"]] * 4, np.float32)
    assert sum(x.duplicate for x in match_palette(many, cat)) == 1


@pytest.mark.parametrize("bad", [[], {"paints": [{"code": "A"}]}, {"paints": [{"code": "A", "hex": "red"}]},
                                 {"paints": [{"code": "A", "hex": "#FFFFFF"}, {"code": "A", "hex": "#000000"}]},
                                 {"paints": [{"code": "A", "lab": [120, 0, 0]}]}])
def test_bad_catalog(bad):
    with pytest.raises(CatalogError):
        parse_catalog(bad)


def test_bundled_starter_palette():
    from paint_by_numbers.palette.catalog import load_catalog
    cat = load_catalog("starter_100")
    assert len(cat) == 100 and len({c["code"] for c in cat}) == 100


def test_select_from_stock_deterministic_and_close():
    from paint_by_numbers.pipeline.color_quantization import select_from_stock
    rng = np.random.default_rng(0)
    stock = rng.uniform([0, -60, -60], [100, 60, 60], (40, 3)).astype(np.float32)
    train = np.concatenate([stock[3] + rng.normal(0, 1, (200, 3)), stock[17] + rng.normal(0, 1, (200, 3)),
                            stock[29] + rng.normal(0, 1, (200, 3))]).astype(np.float32)
    a = select_from_stock(train, None, stock, 3)
    b = select_from_stock(train, None, stock, 3)
    assert list(a) == list(b) == [3, 17, 29]
    assert len(select_from_stock(train, None, stock, 99)) == 40          # k більше за склад


def test_pipeline_uses_exact_stock_colors(tmp_path):
    import cv2
    from paint_by_numbers.generate import generate
    from paint_by_numbers.palette.catalog import load_catalog
    from paint_by_numbers.settings import Settings
    rng = np.random.default_rng(1)
    img = np.full((200, 280, 3), (190, 170, 150), np.uint8)
    cv2.circle(img, (140, 100), 60, (60, 90, 210), -1)
    img = np.clip(img.astype(int) + rng.integers(-8, 8, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(tmp_path / "t.png"), img)
    cat = load_catalog("starter_100")
    res = generate(str(tmp_path / "t.png"), Settings(width_mm=100.0, n_colors=8, catalog=cat, order_number="x"),
                   tmp_path / "o", force=True)
    stock = np.array([c["lab"] for c in cat])
    assert all(np.abs(stock - c).sum(1).min() < 0.01 for c in res.rm.palette_lab)
    assert res.report["catalog"]["max_delta_e2000"] < 0.05 and len(res.rm.palette_lab) <= 8
