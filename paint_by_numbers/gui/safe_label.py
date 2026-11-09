"""Підпис, який ніколи не розпирає панель: довгі імена файлів і шляхи переносяться по рядках.

QLabel із word wrap не вміє переносити «слово» без пробілів (довге імʼя файлу, шлях), тому мінімальна ширина панелі
росла до довжини імені. Тут після роздільників (/ \\ _ - . , ;) і в надто довгих «словах» вставляються невидимі
пробіли нульової ширини (U+200B), а мінімальна ширина підпису дорівнює нулю."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel

ZWSP = "\u200b"
_BREAK_AFTER = set("/\\_-.,;:")
_MAX_WORD = 18


def soft_wrap(text: str) -> str:
    out, run = [], 0
    for ch in text:
        out.append(ch)
        if ch.isspace():
            run = 0
            continue
        run += 1
        if ch in _BREAK_AFTER or run >= _MAX_WORD:
            out.append(ZWSP)
            run = 0
    return "".join(out)


class SafeLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setWordWrap(True)
        self.setText(text)

    def setText(self, text: str) -> None:           # noqa: N802 (Qt-стиль)
        self._full = text or ""
        super().setText(soft_wrap(self._full))
        self.setToolTip(self._full if len(self._full) > 40 else "")

    def text(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:             # noqa: N802
        h = super().minimumSizeHint().height()
        return QSize(0, h)
