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
