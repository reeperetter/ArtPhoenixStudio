import json
import os

import pytest

from paint_by_numbers.palette.catalog import CatalogError, catalog_to_json, load_catalog, paint_hex, save_catalog


def test_catalog_json_roundtrip(tmp_path):
    rows = [{"code": " A1 ", "name": "Білий", "hex": "#f4f3ee", "pigments": "pw6", "strength": ""},
            {"code": "B2", "name": "Синій", "hex": "1c3f9e", "pigments": ["PB29", "pw6"], "strength": "2.5"}]
    p = tmp_path / "x.json"
    save_catalog(p, "Мій набір", rows)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["name"] == "Мій набір"
    assert data["paints"][0] == {"code": "A1", "name": "Білий", "hex": "#F4F3EE", "pigments": ["PW6"]}
    assert data["paints"][1]["strength"] == 2.5 and data["paints"][1]["pigments"] == ["PB29", "PW6"]
    back = load_catalog(p)
    assert [b["code"] for b in back] == ["A1", "B2"]


@pytest.mark.parametrize("rows,fragment", [
    ([], "порожній"),
    ([{"code": "", "hex": "#FFFFFF"}], "code"),
    ([{"code": "A", "hex": "#FFFFFF"}, {"code": "A", "hex": "#000000"}], "повторюється"),
    ([{"code": "A", "hex": "#GG0000"}], "hex"),
    ([{"code": "A", "hex": "#FFFFFF", "pigments": "XYZ"}], "пігмент"),
    ([{"code": "A", "hex": "#FFFFFF", "strength": "99"}], "strength"),
])
def test_validation_messages(rows, fragment):
    with pytest.raises(CatalogError) as e:
        catalog_to_json("n", rows)
    assert fragment in str(e.value)


def test_lab_only_paint_gets_hex():
    h = paint_hex({"lab": [50.0, 0.0, 0.0]})
    assert h.startswith("#") and len(h) == 7 and h[1:3] == h[3:5] == h[5:7]       # нейтральний сірий


def test_editor_dialog(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from paint_by_numbers.gui.palette_editor import CODE, HEX, NAME, PaletteEditor
    QApplication.instance() or QApplication([])
    d = PaletteEditor([])
    assert d.tbl.rowCount() == 1
    d.tbl.item(0, CODE).setText("W")
    d.tbl.item(0, NAME).setText("Білий")
    d.tbl.item(0, HEX).setText("f5f5f0")
    assert d.tbl.item(0, HEX).text() == "#F5F5F0"                   # нормалізація hex
    d.add_row()
    d.tbl.item(1, HEX).setText("#1A1A1A")
    assert "Готово" in d.lbl_info.text()
    d.dup_row()
    assert d.tbl.rowCount() == 3 and d.tbl.item(2, CODE).text() != d.tbl.item(1, CODE).text()
    d.tbl.clearSelection()
    d.tbl.setCurrentCell(2, CODE)
    d.del_rows()
    assert d.tbl.rowCount() == 2
    d.tbl.item(1, HEX).setText("zzz")
    assert d.validate()[0] is None and "⚠" in d.lbl_info.text()     # помилку видно одразу
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a))
    d.apply()
    assert shown                                                      # з помилкою не застосовується
    d.tbl.item(1, HEX).setText("#1A1A1A")
    out = tmp_path / "set.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    got = []
    d.applied.connect(got.append)
    d.apply()
    assert got == [str(out)] and [p["code"] for p in load_catalog(out)] == ["W", "P-02"]
    d2 = PaletteEditor(load_catalog(out), "set", str(out))           # повторне відкриття існуючого файлу
    assert d2.tbl.rowCount() == 2 and d2.tbl.item(0, HEX).text() == "#F5F5F0"
