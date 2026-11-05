import numpy as np
import pytest
from skimage.color import rgb2lab

from paint_by_numbers.export.package import build_package
from paint_by_numbers.generate import generate, run_pipeline
from paint_by_numbers.palette.catalog import CatalogError, parse_catalog
from paint_by_numbers.palette.mixing import MixError, recipe_text, solve_mixes
from paint_by_numbers.purchase import build_purchase_list
from paint_by_numbers.settings import Settings
from tests.test_project import _photo

BASES = [("W", "Білий", "#F5F5F0"), ("K", "Чорний", "#1A1A1A"), ("R", "Червоний", "#C8201E"), ("Y", "Жовтий", "#F2C40E"),
         ("B", "Синій", "#1C3F9E"), ("G", "Зелений", "#2E8B3A"), ("O", "Охра", "#B8842A"), ("N", "Умбра", "#5A3A22")]


def _bases(strength=None):
    rows = [{"code": c, "name": n, "hex": h, **({"strength": strength} if strength else {})} for c, n, h in BASES]
    return parse_catalog(rows)[1]


def _lab(h):
    return rgb2lab(np.array([[[int(h[i:i + 2], 16) for i in (1, 3, 5)]]]) / 255.)[0, 0]


def test_exact_base_is_found_and_parts_sum():
    res, info = solve_mixes(np.array([_lab("#2E8B3A")]), _bases())
    r = res[0]
    assert r.delta_e2000 < 0.5 and len(r.components) == 1
    assert sum(r.parts.values()) == r.total_parts == 12
    assert r.components[0]["ml_per_container"] == 3.0                # вся ємність 3 мл однією фарбою


def test_recipe_volume_matches_container_and_limits():
    t = np.array([_lab("#7A9E3A"), _lab("#D8A070"), _lab("#6A7A9A")])
    for n_max in (1, 2, 3):
        res, _ = solve_mixes(t, _bases(), 12, n_max, 3.0)
        for r in res:
            assert 1 <= len(r.components) <= n_max
            assert abs(sum(c["ml_per_container"] for c in r.components) - 3.0) < 1e-6
            assert all(c["ml_per_container"] >= 0.25 - 1e-9 for c in r.components)         # не менше одного кроку
    # дозволено більше компонентів --- не гірше за менше (з поправкою на штраф)
    r1, _ = solve_mixes(t, _bases(), 12, 1)
    r3, _ = solve_mixes(t, _bases(), 12, 3)
    assert all(b.delta_e2000 <= a.delta_e2000 + 1e-6 for a, b in zip(r1, r3))


def test_deterministic_and_text():
    t = np.array([_lab("#7A9E3A")])
    a, _ = solve_mixes(t, _bases())
    b, _ = solve_mixes(t, _bases())
    assert recipe_text(a[0]) == recipe_text(b[0]) and recipe_text(a[0]).endswith("мл")


def test_strength_changes_recipe():
    t = np.array([_lab("#6A7A9A")])
    a, _ = solve_mixes(t, _bases())
    strong = _bases()
    for p in strong:
        if p["code"] == "B":
            p["strength"] = 4.0
    b, _ = solve_mixes(t, strong)
    assert a[0].parts != b[0].parts


def test_input_validation():
    with pytest.raises(MixError):
        solve_mixes(np.zeros((1, 3)), [])
    with pytest.raises(MixError):
        solve_mixes(np.zeros((1, 3)), _bases(), 12, 9)
    with pytest.raises(CatalogError):
        parse_catalog([{"code": "X", "hex": "#FFFFFF", "strength": 99}])


def test_thinning_large_base():
    rng = np.random.default_rng(3)
    big = parse_catalog([{"code": f"C{i}", "hex": "#%02X%02X%02X" % tuple(rng.integers(0, 255, 3))} for i in range(60)])[1]
    res, info = solve_mixes(np.array([_lab("#7A9E3A")]), big, 8, 3)
    assert info["thinned"] and info["bases_used_in_search"] == 40 and res[0].delta_e2000 < 12


def test_pipeline_package_and_purchase(tmp_path):
    photo = tmp_path / "p.png"
    _photo(photo)
    s = Settings(mode="balanced", n_colors=6, width_mm=120.0, order_number="m1", mix_mode=True, catalog=_bases(),
                 coverage_mm2_per_container=9000.0, safety_factor=1.2)
    res = generate(str(photo), s, tmp_path / "out")
    spec = res.spec
    assert all(p["mix"] for p in spec["paints"]) and all(p["paint_code"].startswith("M-") for p in spec["paints"])
    for p in spec["paints"]:
        comps = p["mix"]["components"]
        assert abs(sum(c["ml_total"] for c in comps) - p["total_ml"]) < 0.01          # весь обсяг розписано по фарбах
        assert p["catalog_delta_e2000"] is not None
    use = spec["base_usage"]
    assert abs(sum(u["ml"] for u in use) - spec["totals"]["total_ml"]) < 0.05
    assert res.report["catalog"]["mode"] == "mix"
    assert (tmp_path / "out" / "order_m1" / "palette" / "base_paints_usage.csv").is_file()
    d = build_purchase_list(tmp_path / "out")
    codes = {e["paint_code"] for e in d["paints"]}
    assert codes <= {c for c, _, _ in BASES}                                           # у закупівлі лише базові фарби
    assert abs(sum(e["total_ml"] for e in d["paints"]) - spec["totals"]["total_ml"]) < 0.05


def test_mix_preview_uses_attainable_colors(tmp_path):
    photo = tmp_path / "p.png"
    _photo(photo)
    s = Settings(mode="draft", n_colors=5, width_mm=100.0, order_number="m2", mix_mode=True, catalog=_bases())
    res = run_pipeline(str(photo), s)
    pred = {tuple(np.round(p["lab"], 1)) for p in res.spec["paints"]}
    assert len(pred) == len(res.spec["paints"])


def test_gui_mix_settings(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from paint_by_numbers.gui.main_window import MainWindow
    from paint_by_numbers.gui.prefs import Prefs
    QApplication.instance() or QApplication([])
    w = MainWindow(Prefs(str(tmp_path / "p.ini")))
    assert not w.make_settings().mix_mode
    w.cb_mix.setChecked(True)
    w.sp_mix_n.setValue(2)
    w.sp_mix_parts.setValue(6)
    s = w.make_settings()
    assert s.mix_mode and s.mix_max_components == 2 and s.mix_parts == 6
    w._save_prefs()
    w2 = MainWindow(Prefs(str(tmp_path / "p.ini")))
    assert w2.cb_mix.isChecked() and w2.sp_mix_n.value() == 2
