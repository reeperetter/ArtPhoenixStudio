import logging

from paint_by_numbers import applog


def test_sanitize_strips_dirs():
    t = applog.sanitize('File "C:\\Users\\Ivan\\Photos\\wedding.jpg", and /home/ivan/pics/a.jpg')
    assert "Ivan" not in t and "ivan" not in t.replace("<dir>", "")
    assert "wedding.jpg" in t


def test_log_exception_writes_file(tmp_path):
    lg = logging.getLogger(applog.LOGGER)
    for h in list(lg.handlers):
        lg.removeHandler(h)
    p = tmp_path / "errors.log"
    applog.setup(p)
    try:
        raise ValueError("boom /home/secretuser/x/photo.jpg")
    except ValueError as e:
        applog.log_exception(e, "тест")
    for h in lg.handlers:
        h.flush()
    txt = p.read_text(encoding="utf-8")
    assert "ValueError" in txt and "boom" in txt and "secretuser" not in txt
    for h in list(lg.handlers):
        lg.removeHandler(h)
        h.close()


def test_third_party_notices_present():
    from pathlib import Path
    t = (Path(applog.__file__).parent / "assets" / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for name in ("NumPy", "OpenCV", "PySide6", "ReportLab"):
        assert name in t
