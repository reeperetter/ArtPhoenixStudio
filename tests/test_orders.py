import json

import pytest

from paint_by_numbers import orders


def mk(root, name, num, title, created):
    d = root / name / "project"
    d.mkdir(parents=True)
    (d / "project.json").write_text(json.dumps({"order_number": num, "project_name": title, "created": created}), encoding="utf-8")
    (root / name / "source").mkdir()
    (root / name / "source" / "a.jpg").write_bytes(b"x")
    return root / name


def test_find_and_search(tmp_path):
    mk(tmp_path, "order_000001", "000001", "Весілля Іваненків", "2026-01-01")
    mk(tmp_path / "2026", "order_000002", "000002", "Кіт Мурзик", "2026-02-01")
    (tmp_path / "other").mkdir()
    allr = orders.find_orders(tmp_path)
    assert [i["order_number"] for i in allr] == ["000002", "000001"]
    assert [i["order_number"] for i in orders.find_orders(tmp_path, "мурзик")] == ["000002"]
    assert [i["order_number"] for i in orders.find_orders(tmp_path, "0001")] == ["000001"]
    assert orders.find_orders(tmp_path, "нема") == []


def test_recent():
    r = orders.add_recent(["a", "b"], "b")
    assert r == ["b", "a"]
    assert len(orders.add_recent([str(i) for i in range(20)], "x")) == orders.MAX_RECENT
    assert orders.parse_recent("not json") == [] and orders.parse_recent('["a", 1]') == ["a"]


def test_delete_safety(tmp_path):
    d = mk(tmp_path, "order_000001", "000001", "t", "2026")
    with pytest.raises(orders.OrderError):
        orders.delete_order(tmp_path)                       # не замовлення
    plain = tmp_path / "order_999"
    plain.mkdir()
    with pytest.raises(orders.OrderError):
        orders.delete_order(plain)                          # немає project.json
    orders.delete_order(d)
    assert not d.exists() and plain.exists()


def test_orders_dialog(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from paint_by_numbers.gui.orders_dialog import OrdersDialog
    QApplication.instance() or QApplication([])
    d = mk(tmp_path, "order_000001", "000001", "Кіт", "2026-01-01")
    dlg = OrdersDialog(str(tmp_path))
    assert dlg.tbl.rowCount() == 1
    dlg.ed_q.setText("zzz")
    assert dlg.tbl.rowCount() == 0
    dlg.ed_q.setText("кіт")
    dlg.tbl.setCurrentCell(0, 0)
    got = []
    dlg.openRequested.connect(got.append)
    dlg.open_selected()
    assert got == [str(d)]
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No)
    dlg.delete_selected()
    assert d.exists()
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dlg.delete_selected()
    assert not d.exists() and dlg.tbl.rowCount() == 0
