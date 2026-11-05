import numpy as np

from paint_by_numbers import autosave
from paint_by_numbers.generate import run_pipeline
from paint_by_numbers.project import open_project
from paint_by_numbers.settings import Settings
from tests.test_project import _photo


def test_snapshot_roundtrip_without_photo_copy(tmp_path):
    photo = tmp_path / "customer.png"
    _photo(photo)
    s = Settings(width_mm=100.0, order_number="777")
    res = run_pipeline(str(photo), s)
    root = tmp_path / "rec"
    assert not autosave.has_recovery(root)
    autosave.snapshot(res, photo, "customer.png", root)
    assert autosave.has_recovery(root)
    assert not list(root.rglob("*.png")) and not list(root.rglob("*.jpg"))    # фото клієнта не копіюється
    back = open_project(root)
    assert back.settings.order_number == "777"
    assert np.array_equal(back.rm.labels, res.rm.labels)
    autosave.snapshot(res, photo, "customer.png", root)                       # повторний запис замінює знімок
    assert not (root.with_name("rec.tmp")).exists()
    autosave.clear(root)
    assert not root.exists()


def test_snapshot_async_logs_not_raises(tmp_path):
    class Bad:
        settings = None
    autosave.snapshot_async(Bad(), tmp_path / "x.png", None, tmp_path / "rec").join(5)
    assert not autosave.has_recovery(tmp_path / "rec")


def test_gui_offer_recovery(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from paint_by_numbers.gui.main_window import MainWindow
    from paint_by_numbers.gui.prefs import Prefs
    QApplication.instance() or QApplication([])
    rec = tmp_path / "rec"
    monkeypatch.setattr(autosave, "recovery_dir", lambda: rec)
    photo = tmp_path / "c.png"
    _photo(photo)
    autosave.snapshot(run_pipeline(str(photo), Settings(width_mm=100.0, order_number="9")), photo, "c.png", rec)
    win = MainWindow(Prefs(str(tmp_path / "p1.ini")))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    win.offer_recovery()
    assert not autosave.has_recovery(rec)                     # «Ні» видаляє знімок
    autosave.snapshot(run_pipeline(str(photo), Settings(width_mm=100.0, order_number="9")), photo, "c.png", rec)
    win._unsaved = False
    win.close()
    assert not autosave.has_recovery(rec)                     # чисте закриття теж видаляє
    win2 = MainWindow(Prefs(str(tmp_path / "p2.ini")))
    autosave.snapshot(run_pipeline(str(photo), Settings(width_mm=100.0, order_number="9")), photo, "c.png", rec)
    win2._unsaved = True
    win2.close()
    assert autosave.has_recovery(rec)                         # незбережені правки: знімок лишається


def test_overlay_contours(tmp_path):
    import numpy as np
    from paint_by_numbers.export.preview import overlay_contours
    orig = np.full((50, 100, 3), 200, np.uint8)
    cont = np.full((100, 200, 3), 255, np.uint8)
    cont[40:44, :] = 0                                   # чорна лінія
    out = overlay_contours(orig, cont)
    assert out.shape == cont.shape
    assert tuple(out[42, 10]) == (40, 40, 235)           # лінія зафарбована
    assert tuple(out[5, 10]) == (200, 200, 200)          # решта --- оригінал
