import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import cv2
import numpy as np

from paint_by_numbers.gui import zone_utils as zu
from paint_by_numbers.gui.prefs import Prefs


def test_zone_utils_roundtrip():
    z = zu.rect_zone((50, 80), (150, 40), 200, 100, "r", 2.0)
    assert z["x0"] == 0.25 and z["x1"] == 0.75 and z["y0"] == 0.4 and z["y1"] == 0.8
    assert zu.rect_zone((10, 10), (12, 12), 200, 100, "tiny", 2.0) is None            # випадковий клік
    e = zu.ellipse_zone((0, 0), (100, 50), 200, 100, "e", 1.0)
    assert (e["cx"], e["cy"], e["rx"], e["ry"]) == (0.25, 0.25, 0.25, 0.25)
    assert zu.polygon_zone([(0, 0), (10, 0)], 100, 100, "p", 1.0) is None
    assert zu.point_in_zone(z, 100, 60, 200, 100) and not zu.point_in_zone(z, 10, 10, 200, 100)
    # зону з обмеженням за краями полотна
    assert zu.rect_zone((-50, -50), (500, 500), 200, 100, "big", 1.0)["x1"] == 1.0


def _wait(win, cond, timeout=120):
    from PySide6.QtWidgets import QApplication
    t0 = time.time()
    while not cond():
        QApplication.processEvents()
        time.sleep(0.02)
        assert time.time() - t0 < timeout, "timeout"


def test_window_end_to_end(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from paint_by_numbers.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    rng = np.random.default_rng(3)
    img = np.full((300, 400, 3), (200, 170, 120), np.uint8)
    cv2.circle(img, (200, 150), 80, (40, 60, 200), -1)
    img = np.clip(img.astype(int) + rng.integers(-10, 10, img.shape), 0, 255).astype(np.uint8)
    photo = tmp_path / "p.png"
    cv2.imwrite(str(photo), img)

    w = MainWindow(Prefs(str(tmp_path / 'prefs.ini')))
    w.show()
    w.open_photo(str(photo))
    w.sp_w.setValue(120)
    w.cb_auto_colors.setChecked(False)
    w.sp_colors.setValue(8)
    # імітація малювання зони миші
    w.canvas.set_tool("ellipse")
    z = zu.ellipse_zone((120, 70), (280, 230), w.canvas.img_w, w.canvas.img_h, "", 2.0)
    w.canvas.zoneDrawn.emit(z)
    assert len(w.zones) == 1 and w.lst_zones.count() == 1 and w.zones[0]["name"] == "Зона 1"
    w.sp_zw.setValue(3.0)
    assert w.zones[0]["weight"] == 3.0
    w.generate()
    _wait(w, lambda: w.res is not None and w.job is None)
    assert w.res.report["priority_zones"] is not None and w.tbl.rowCount() == len(w.res.spec["paints"])
    assert w.btn_save.isEnabled()
    w.sp_k.setValue(1.5)                                  # зміна налаштувань скасовує превʼю
    assert w.res is None and not w.btn_save.isEnabled()
    w.generate()
    _wait(w, lambda: w.res is not None and w.job is None)
    w.save_package(str(tmp_path / "out"))
    _wait(w, lambda: w.job is None and (tmp_path / "out" / "order_000001" / "print" / "canvas_outline.svg").exists())
    assert (tmp_path / "out" / "order_000001" / "production" / "production_specification.pdf").exists()
    w.grab().save(str(tmp_path / "shot.png"))
    w.close()


def test_window_compare_variants(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    import paint_by_numbers.gui.main_window as mw
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    # два варіанти замість дев'яти, щоб тест був швидким
    real = mw.default_variants
    monkeypatch.setattr(mw, "default_variants", lambda s: real(s, ["simple"], [6, 8]))
    rng = np.random.default_rng(4)
    img = np.full((240, 320, 3), (200, 160, 120), np.uint8)
    cv2.circle(img, (160, 120), 70, (40, 60, 200), -1)
    img = np.clip(img.astype(int) + rng.integers(-10, 10, img.shape), 0, 255).astype(np.uint8)
    photo = tmp_path / "c.png"
    cv2.imwrite(str(photo), img)
    w = mw.MainWindow(Prefs(str(tmp_path / 'prefs.ini')))
    w.show()
    w.open_photo(str(photo))
    w.sp_w.setValue(100)
    w.compare_variants()
    _wait(w, lambda: w.variant_rows and w.res is not None and w.job is None, timeout=180)
    assert w.tbl_var.rowCount() == 2 and not w.cb_auto_colors.isChecked()
    assert w.sp_colors.value() in (6, 8) and w.res.settings.colors == w.sp_colors.value()
    w.close()


def test_prefs_roundtrip_and_corruption(tmp_path):
    ini = tmp_path / "p.ini"
    p = Prefs(str(ini))
    assert p.get("width_mm") == 300.0 and p.get("mode") == "balanced" and p.get("auto_height") is True
    p.set("width_mm", 450.0)
    p.set("auto_height", False)
    p.set("colors", 30)
    p.sync()
    q = Prefs(str(ini))
    assert q.get("width_mm") == 450.0 and q.get("auto_height") is False and q.get("colors") == 30
    # пошкоджені значення замінюються типовими
    q.set("width_mm", "abc")
    q.set("colors", 999)
    q.set("mode", "turbo")
    q.set("safety_factor", 0.2)
    q.set("coverage_confirmed", "maybe")
    assert (q.get("width_mm"), q.get("colors"), q.get("mode"), q.get("safety_factor")) == (300.0, 24, "balanced", 1.3)
    assert q.get("coverage_confirmed") is False
    with pytest.raises(KeyError):
        q.set("nope", 1)
    q.reset()
    assert q.get("width_mm") == 300.0


def test_window_restores_settings(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from paint_by_numbers.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    ini = str(tmp_path / "w.ini")
    cat = tmp_path / "cat.json"
    cat.write_text('{"paints":[{"code":"A","hex":"#FF0000"},{"code":"B","hex":"#00FF00"}]}', encoding="utf-8")

    w = MainWindow(Prefs(ini))
    w.sp_w.setValue(420)
    w.cb_auto_h.setChecked(False)
    w.sp_h.setValue(560)
    w.cmb_mode.setCurrentIndex(2)
    w.cb_auto_colors.setChecked(False)
    w.sp_colors.setValue(40)
    w.sp_cov.setValue(15000)
    w.sp_k.setValue(1.5)
    w.cb_cov_ok.setChecked(True)
    w.prefs.set("catalog_path", str(cat))
    w.resize(1111, 777)
    w.close()

    w2 = MainWindow(Prefs(ini))
    assert (w2.sp_w.value(), w2.sp_h.value(), w2.cmb_mode.currentData(), w2.sp_colors.value()) == (420, 560, "detailed", 40)
    assert not w2.cb_auto_h.isChecked() and w2.sp_h.isEnabled() and not w2.cb_auto_colors.isChecked() and w2.sp_colors.isEnabled()
    assert w2.sp_cov.value() == 15000 and w2.sp_k.value() == 1.5 and w2.cb_cov_ok.isChecked()
    assert len(w2.catalog) == 2 and "cat.json" in w2.lbl_cat.text()
    s = w2.make_settings()
    assert s.mode == "detailed" and s.n_colors == 40 and s.height_mm == 560 and len(s.catalog) == 2
    w2.reset_prefs()
    assert w2.sp_w.value() == 300 and w2.cb_auto_h.isChecked() and w2.cmb_mode.currentData() == "balanced"
    # каталог, що зник, не ламає запуск
    w2.prefs.set("catalog_path", str(tmp_path / "gone.json"))
    w2.close()
    w3 = MainWindow(Prefs(ini))
    assert w3.catalog == [] and "недоступний" in w3.lbl_cat.text()
    w3.close()


def _mouse(view, kind, x, y, button=None, buttons=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    B = Qt.MouseButton
    typ = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
           "release": QEvent.Type.MouseButtonRelease, "dbl": QEvent.Type.MouseButtonDblClick}[kind]
    btn = button if button is not None else B.LeftButton
    held = buttons if buttons is not None else (B.NoButton if kind == "release" else btn)
    pos = QPointF(x, y)
    e = QMouseEvent(typ, pos, view.viewport().mapToGlobal(pos), btn if kind != "move" else B.NoButton, held,
                    Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view.viewport(), e)


def test_hand_tool_pans_even_when_fitted_and_other_tools_draw(qtbot=None):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from paint_by_numbers.gui.canvas_view import ZoneCanvas
    app = QApplication.instance() or QApplication([])
    v = ZoneCanvas()
    v.resize(600, 500)
    v.show()
    v.set_image(np.full((1200, 900, 3), 128, np.uint8))
    app.processEvents()
    hs, vs = v.horizontalScrollBar(), v.verticalScrollBar()
    # 1) рука працює навіть коли зображення цілком вміщене у вікно
    v.set_tool("pan")
    h0, v0 = hs.value(), vs.value()
    _mouse(v, "press", 300, 250)
    _mouse(v, "move", 260, 210, buttons=Qt.MouseButton.LeftButton)
    _mouse(v, "move", 220, 170, buttons=Qt.MouseButton.LeftButton)
    _mouse(v, "release", 220, 170)
    assert (hs.value() - h0, vs.value() - v0) == (80, 80)        # зображення йде за мишею
    # 2) подвійний клік вміщує зображення
    v.scale(3, 3)
    _mouse(v, "dbl", 300, 250)
    assert v.transform().m11() < 1.0
    # 3) середня кнопка рухає зображення в будь-якому інструменті, а лівою малюється зона
    v.set_tool("rect")
    h0 = hs.value()
    M = Qt.MouseButton.MiddleButton
    _mouse(v, "press", 300, 250, button=M)
    _mouse(v, "move", 270, 250, buttons=M)
    _mouse(v, "release", 270, 250, button=M)
    assert hs.value() - h0 == 30
    got = []
    v.zoneDrawn.connect(got.append)
    _mouse(v, "press", 250, 150)
    _mouse(v, "move", 350, 250, buttons=Qt.MouseButton.LeftButton)
    _mouse(v, "release", 350, 250)
    assert len(got) == 1 and got[0]["shape"] == "rect"


def test_zone_edit_utils():
    w, h = 200.0, 100.0
    r = zu.rect_zone((40, 20), (120, 60), w, h, "r", 2.0)
    m = zu.move_zone(r, 1000, -1000, w, h)                      # зсув упирається в межі полотна
    assert abs(m["x1"] - 1.0) < 1e-9 and abs(m["y0"]) < 1e-9 and abs((m["x1"] - m["x0"]) - (r["x1"] - r["x0"])) < 1e-9
    d = zu.drag_handle(r, "se", 160, 90, w, h)
    assert (d["x0"], d["y0"], d["x1"], d["y1"]) == (0.2, 0.2, 0.8, 0.9)
    d = zu.drag_handle(r, "nw", 500, 500, w, h)                 # не можна перекинути за протилежний край
    assert d["x1"] * w - d["x0"] * w >= zu.MIN_SIZE_PX - 1e-9 and d["y1"] * h - d["y0"] * h >= zu.MIN_SIZE_PX - 1e-9
    e = zu.ellipse_zone((40, 20), (120, 60), w, h, "e", 2.0)
    d = zu.drag_handle(e, "e", 180, 40, w, h)
    assert abs((d["cx"] + d["rx"]) * w - 180) < 1e-9 and abs(d["cy"] - e["cy"]) < 1e-9
    p = zu.polygon_zone([(10, 10), (100, 10), (50, 80)], w, h, "p", 2.0)
    d = zu.drag_handle(p, ("v", 2), 60, 90, w, h)
    assert d["points"][2] == [0.3, 0.9] and d["points"][0] == p["points"][0]
    assert len(zu.handles(r, w, h)) == 8 and len(zu.handles(p, w, h)) == 3
    rot = dict(e, angle=30.0)
    assert zu.handles(rot, w, h) == [] and zu.move_zone(rot, 5, 5, w, h)["cx"] > e["cx"]


def test_zone_editing_with_mouse():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from paint_by_numbers.gui.canvas_view import ZoneCanvas
    app = QApplication.instance() or QApplication([])
    v = ZoneCanvas()
    v.resize(600, 500)
    v.show()
    v.set_image(np.full((400, 300, 3), 128, np.uint8))
    app.processEvents()
    z = zu.rect_zone((100, 100), (200, 200), 300, 400, "z", 2.0)
    zones = [z]
    v.set_zones(zones, -1)
    v.set_tool("select")
    edited, clicked = [], []
    v.zoneEdited.connect(edited.append)
    v.zoneClicked.connect(clicked.append)

    def to_view(x, y):
        p = v.mapFromScene(x, y)
        return p.x(), p.y()
    L = Qt.MouseButton.LeftButton
    # клік усередині вибирає, подальше перетягування зсуває
    x, y = to_view(150, 150)
    _mouse(v, "press", x, y)
    assert clicked == [0]
    v.set_zones(zones, 0)
    x2, y2 = to_view(150 + 30, 150 + 20)
    _mouse(v, "move", x2, y2, buttons=L)
    _mouse(v, "release", x2, y2)
    assert edited == [0] and abs(zones[0]["x0"] * 300 - 130) < 1.5 and abs(zones[0]["y0"] * 400 - 120) < 1.5
    # ручка «se» змінює розмір
    hx, hy = to_view(zones[0]["x1"] * 300, zones[0]["y1"] * 400)
    _mouse(v, "press", hx, hy)
    tx, ty = to_view(zones[0]["x1"] * 300 + 40, zones[0]["y1"] * 400 + 30)
    _mouse(v, "move", tx, ty, buttons=L)
    _mouse(v, "release", tx, ty)
    assert edited == [0, 0] and abs(zones[0]["x1"] * 300 - 270) < 1.5 and abs(zones[0]["y1"] * 400 - 250) < 1.5
    assert abs(zones[0]["x0"] * 300 - 130) < 1.5            # протилежний край не зрушив
    # Delete просить видалити вибрану зону
    asked = []
    v.deleteRequested.connect(asked.append)
    from PySide6.QtTest import QTest
    v.setFocus()
    QTest.keyClick(v, Qt.Key.Key_Delete)
    assert asked == [0]


def test_window_opens_project_without_recalculation(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from paint_by_numbers.generate import generate
    from paint_by_numbers.gui.main_window import MainWindow
    from paint_by_numbers.settings import Settings
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    rng = np.random.default_rng(6)
    img = np.full((240, 320, 3), (200, 160, 120), np.uint8)
    cv2.circle(img, (160, 120), 70, (40, 60, 200), -1)
    img = np.clip(img.astype(int) + rng.integers(-10, 10, img.shape), 0, 255).astype(np.uint8)
    photo = tmp_path / "orig.png"
    cv2.imwrite(str(photo), img)
    z = [{"name": "центр", "shape": "rect", "x0": 0.3, "y0": 0.3, "x1": 0.7, "y1": 0.7, "weight": 3.0}]
    a = generate(str(photo), Settings(mode="detailed", n_colors=10, width_mm=100.0, order_number="777",
                                      project_name="Тест", coverage_mm2_per_container=8000.0, safety_factor=1.4,
                                      zones=z), tmp_path / "out")
    w = MainWindow(Prefs(str(tmp_path / "pp.ini")))
    w.show()
    w.open_project_dialog(str(tmp_path / "out" / "order_777"))
    _wait(w, lambda: w.res is not None and w.job is None)
    assert w.cmb_mode.currentData() == "detailed" and w.sp_colors.value() == 10 and not w.cb_auto_colors.isChecked()
    assert w.sp_w.value() == 100 and w.cb_auto_h.isChecked() and w.sp_cov.value() == 8000 and w.sp_k.value() == 1.4
    assert w.ed_order.text() == "777" and w.ed_name.text() == "Тест"
    assert len(w.zones) == 1 and w.zones[0]["name"] == "центр" and w.lst_zones.count() == 1
    assert w.res.report["regions_final"] == a.report["regions_final"] and w.tbl.rowCount() == len(a.spec["paints"])
    assert w.btn_save.isEnabled() and w.original_name == "orig.png" and "без перерахунку" in w.lbl_status.text()
    # результат лишається чинним, поки налаштування не змінено
    QApplication.processEvents()
    assert w.res is not None
    w.sp_k.setValue(1.6)
    assert w.res is None
    # пошкоджена папка: зрозуміле повідомлення й вікно залишається робочим
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    w.open_project_dialog(str(tmp_path))
    _wait(w, lambda: w.job is None)
    assert shown and "project.json" in shown[0]
    w.close()


def test_window_undo_redo_zones(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from paint_by_numbers.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    img = np.full((300, 400, 3), 120, np.uint8)
    photo = tmp_path / "u.png"
    cv2.imwrite(str(photo), img)
    w = MainWindow(Prefs(str(tmp_path / "u.ini")))
    w.show()
    w.open_photo(str(photo))
    assert not w.btn_undo.isEnabled() and not w.btn_redo.isEnabled()
    W, H = w.canvas.img_w, w.canvas.img_h
    w.canvas.zoneDrawn.emit(zu.rect_zone((40, 40), (140, 120), W, H, "", 2.0))
    w.canvas.zoneDrawn.emit(zu.ellipse_zone((160, 100), (300, 240), W, H, "", 2.0))
    assert len(w.zones) == 2 and w.btn_undo.isEnabled()
    w.undo_zones()
    assert len(w.zones) == 1 and w.lst_zones.count() == 1 and w.btn_redo.isEnabled()
    w.redo_zones()
    assert len(w.zones) == 2 and w.zones[1]["shape"] == "ellipse"
    # швидкі зміни ваги --- один крок історії
    w.lst_zones.setCurrentRow(1)
    for v in (2.5, 3.0, 3.5, 4.0):
        w.sp_zw.setValue(v)
    assert w.zones[1]["weight"] == 4.0
    w.undo_zones()
    assert w.zones[1]["weight"] == 2.0 and len(w.zones) == 2
    w.redo_zones()
    assert w.zones[1]["weight"] == 4.0
    # перетягування зони можна відмінити
    w.canvas.set_tool("select")
    before = dict(w.zones[0])
    p0 = w.canvas.mapFromScene(90, 80)
    p1 = w.canvas.mapFromScene(110, 95)
    w.lst_zones.setCurrentRow(0)
    _mouse(w.canvas, "press", p0.x(), p0.y())
    _mouse(w.canvas, "move", p1.x(), p1.y(), buttons=Qt.MouseButton.LeftButton)
    _mouse(w.canvas, "release", p1.x(), p1.y())
    assert w.zones[0]["x0"] != before["x0"]
    w.undo_zones()
    assert abs(w.zones[0]["x0"] - before["x0"]) < 1e-9 and abs(w.zones[0]["y1"] - before["y1"]) < 1e-9
    # видалення відміняється з поверненням зони на місце
    w.delete_zone()
    assert len(w.zones) == 1
    w.undo_zones()
    assert len(w.zones) == 2 and w.zones[1]["weight"] == 4.0
    # відміна скасовує превʼю, бо набір зон змінився
    w.res = object()
    w.undo_zones()
    assert w.res is None
    # гарячі клавіші справді працюють: Ctrl+Z, Ctrl+Y та Ctrl+Shift+Z
    from PySide6.QtTest import QTest
    n = len(w.zones)
    w.activateWindow()
    w.canvas.setFocus()
    CT, SH = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(w.canvas, Qt.Key.Key_Z, CT)
    QApplication.processEvents()
    assert len(w.zones) == n - 1 or w.zones != w.history._items[-1].state[0]
    QTest.keyClick(w.canvas, Qt.Key.Key_Y, CT)
    QApplication.processEvents()
    QTest.keyClick(w.canvas, Qt.Key.Key_Z, CT)
    QTest.keyClick(w.canvas, Qt.Key.Key_Z, CT | SH)
    QApplication.processEvents()
    assert w.history.can_undo
    w.close()


def test_batch_dialog(tmp_path, monkeypatch):
    import json as _json
    from PySide6.QtWidgets import QApplication
    from paint_by_numbers.gui.batch_dialog import BatchDialog
    from paint_by_numbers.settings import Settings
    app = QApplication.instance() or QApplication([])
    d = tmp_path / "in"
    d.mkdir()
    for i in range(3):
        rng = np.random.default_rng(i)
        img = np.full((200, 280, 3), (200, 160, 120), np.uint8)
        cv2.circle(img, (140, 100), 50 + i * 5, (40, 60, 200), -1)
        cv2.imwrite(str(d / f"p{i}.png"), np.clip(img.astype(int) + rng.integers(-8, 8, img.shape), 0, 255).astype(np.uint8))
    (d / "p1.zones.json").write_text("{плохий json")
    prefs = Prefs(str(tmp_path / "b.ini"))
    dlg = BatchDialog(Settings(width_mm=100.0, n_colors=6, zones=[{"shape": "rect"}]), prefs)
    assert dlg.base.zones == [] and not dlg.btn_start.isEnabled()
    dlg.set_source(str(d))
    assert dlg.tbl.rowCount() == 3 and dlg.tbl.item(1, 2).text() == "помилка" and not dlg.btn_start.isEnabled()
    dlg.set_out(str(tmp_path / "result"))
    assert dlg.btn_start.isEnabled()
    dlg.show()
    dlg.start()
    assert dlg.job is not None and dlg.btn_cancel.isEnabled() and not dlg.btn_close.isEnabled()
    _wait(dlg, lambda: dlg.job is None and dlg.rows, timeout=180)
    assert [r["status"] for r in dlg.rows] == ["ok", "error", "ok"] and dlg.exit_code() == 2
    assert dlg.tbl.item(0, 2).text() == "готово" and dlg.tbl.item(0, 3).text()
    assert (tmp_path / "result" / "batch_report.csv").exists() and (tmp_path / "result" / "order_p2").is_dir()
    assert dlg.btn_close.isEnabled() and "Готово: 2 з 3" in dlg.lbl_status.text()
    dlg.close()


def test_window_manual_region_editing(tmp_path, monkeypatch):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QMessageBox
    from paint_by_numbers.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    def boom(*a, **k):
        raise AssertionError(f"модальне вікно помилки: {a}")
    monkeypatch.setattr(QMessageBox, "critical", boom)       # модальне вікно підвісило б тест
    rng = np.random.default_rng(3)
    img = np.full((300, 400, 3), (200, 170, 120), np.uint8)
    cv2.circle(img, (200, 150), 80, (40, 60, 200), -1)
    img = np.clip(img.astype(int) + rng.integers(-10, 10, img.shape), 0, 255).astype(np.uint8)
    photo = tmp_path / "p.png"
    cv2.imwrite(str(photo), img)
    w = MainWindow(Prefs(str(tmp_path / "prefs.ini")))
    w.show()
    w.open_photo(str(photo))
    w.sp_w.setValue(120)
    w.cb_auto_colors.setChecked(False)
    w.sp_colors.setValue(8)
    w.generate()
    _wait(w, lambda: w.res is not None and w.job is None, 60)
    assert w.edit_panel.isEnabled() and w.edit_panel.cmb.count() >= len(w.seg.palette_lab)
    n0, c0 = w.res.report["regions_final"], len(w.seg.palette_lab)

    # злиття: вибираємо найбільшу ділянку й сусідню через сигнали панелі
    seg = w.seg
    big = int(np.argmax(w.res.rm.area_px))
    nb = sorted(seg.neighbors(big))[0]
    def center(r):
        ys, xs = np.nonzero(seg.labels == r)
        i = len(xs) // 2
        return float(xs[i]), float(ys[i])
    w.tabs.setCurrentWidget(w.edit_panel)
    w.edit_panel.set_tool("merge")
    w.edit_panel._picked(*center(big))          # перший клік: ділянку виділено
    assert w.edit_panel.view._hl
    w.edit_panel._picked(*center(nb))           # другий клік: злиття
    _wait(w, lambda: w.job is None and w.res.report.get("manual_edits") == 1, 60)
    assert w.res.report["regions_final"] < n0
    assert w.seg_history.can_undo and w.edit_panel.btn_undo.isEnabled()

    # Ctrl+Z на вкладці редагування скасовує правку, повтор повертає
    w.undo_zones()
    _wait(w, lambda: w.job is None and w.res.report["regions_final"] == n0, 60)
    assert w.res.report["manual_edits"] == 0         # після скасування діючих правок немає
    w.redo_zones()
    _wait(w, lambda: w.job is None and w.res.report["regions_final"] < n0, 60)
    assert w.res.report["manual_edits"] == 1

    # неможливе злиття (не сусідні/та сама ділянка) не змінює результат й не падає
    before = w.res
    w.edit_panel.set_tool("merge")
    w.edit_panel._picked(*center(0))
    w.edit_panel._picked(*center(0))
    assert w.res is before and "не застосовано" in w.lbl_status.text()

    # полігон і зміна кольору
    w.edit_panel.set_tool("polygon")
    w.edit_panel.polygonRequested.emit([(10, 10), (60, 10), (60, 50), (10, 50)], 0)
    _wait(w, lambda: w.job is None and w.res.report.get("manual_edits") == 2, 60)

    # нове превʼю після правок питає підтвердження; відмова нічого не скидає
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    r = w.res
    w.generate()
    assert w.res is r and w.job is None
    w.close()
