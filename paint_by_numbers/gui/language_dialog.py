"""Вибір мови інтерфейсу (показується при першому запуску; двомовне, бо мова ще не обрана)."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from ..i18n import LANGUAGES
from . import branding


class LanguageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{branding.APP_NAME}: Мова / Language")
        self.setWindowIcon(branding.app_icon())
        self.chosen: str | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(branding.logo_pixmap(72))
        logo.setAlignment(logo.alignment().AlignHCenter)
        v.addWidget(logo)
        txt = QLabel("Оберіть мову інтерфейсу<br>Choose the interface language")
        txt.setAlignment(txt.alignment().AlignHCenter)
        v.addWidget(txt)
        for code, name in LANGUAGES.items():
            b = QPushButton(name)
            b.setMinimumHeight(40)
            b.setMinimumWidth(240)
            b.clicked.connect(lambda _=False, c=code: self._pick(c))
            v.addWidget(b)
        note = QLabel("<span style='color:gray'>Мову можна змінити пізніше: Файл → Мова / File → Language</span>")
        note.setAlignment(note.alignment().AlignHCenter)
        v.addWidget(note)

    def _pick(self, code: str) -> None:
        self.chosen = code
        self.accept()


def choose_language() -> str:
    dlg = LanguageDialog()
    dlg.exec()
    return dlg.chosen or "uk"
