import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import cv2
import numpy as np

from paint_by_numbers.gui import zone_utils as zu


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

    w = MainWindow()
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
