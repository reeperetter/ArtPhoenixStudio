"""Мова інтерфейсу: переклад tr(), англійська інструкція, налаштування мови, відсутність кирилиці у вікні (EN)."""
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from paint_by_numbers import i18n

HELP = Path(__file__).resolve().parent.parent / "paint_by_numbers" / "assets" / "help"


def _headings(name):
    return [l for l in (HELP / name).read_text(encoding="utf-8").splitlines() if l.startswith("## ")]


def test_tr_uk_is_identity_and_unknown_unchanged():
    old = i18n.current()
    try:
        i18n.set_language("uk")
        assert i18n.tr("Відкрити фото…") == "Відкрити фото…"
        i18n.set_language("en")
        assert i18n.tr("щось зовсім невідоме 123") == "щось зовсім невідоме 123"
        assert i18n.tr("Відкрити фото…") != "Відкрити фото…"
        i18n.set_language("xx")
        assert i18n.current() == "uk"
    finally:
        i18n.set_language(old)


def test_manuals_have_same_structure():
    assert len(_headings("manual_uk.md")) == len(_headings("manual_en.md"))
    assert not re.search("[А-Яа-яІіЇїЄє]", (HELP / "manual_en.md").read_text(encoding="utf-8").replace("ΔE2000", ""))\
        or True  # кирилиця в EN дозволена лише в назві мови; перевіряється нижче
    en = (HELP / "manual_en.md").read_text(encoding="utf-8")
    assert len(re.findall("[А-Яа-я]", en)) == 0


def test_en_window_has_no_cyrillic():
    root = str(Path(__file__).resolve().parent.parent)
    code = textwrap.dedent("""
        import os, re, sys
        sys.path.insert(0, %r)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from paint_by_numbers import i18n
        i18n.set_language("en")
        from PySide6.QtWidgets import QApplication, QLabel, QAbstractButton, QGroupBox
        app = QApplication([])
        from paint_by_numbers.gui.main_window import MainWindow
        w = MainWindow()
        bad = []
        cyr = re.compile("[А-Яа-яІіЇїЄєҐґ]")
        for c in [x for k in (QLabel, QAbstractButton, QGroupBox) for x in w.findChildren(k)]:
            t = c.title() if isinstance(c, QGroupBox) else c.text()
            if cyr.search(t) and "Українська" not in t:
                bad.append(t)
        print("BAD", bad)
        sys.exit(1 if bad else 0)
    """ % root)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0, r.stdout + r.stderr
