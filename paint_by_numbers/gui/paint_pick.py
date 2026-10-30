"""Діалог вибору нового кольору для кольору палітри картини: фарба зі складу (каталогу) або власний колір."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from ..edit import hex_to_lab
from ..i18n import tr


def _swatch(hx: str, size: int = 22) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(hx))
    return QIcon(pm)


class PaintPickDialog(QDialog):
    """catalog: список фарб складу ({code,name,hex,lab}); current_hex: колір, який міняємо."""

    def __init__(self, title: str, current_hex: str, catalog: list[dict], used_labs: np.ndarray, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 520)
        self.result_lab: list[float] | None = None
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        cur = QLabel()
        cur.setPixmap(_swatch(current_hex, 36).pixmap(36, 36))
        row.addWidget(QLabel(tr("Поточний колір:")))
        row.addWidget(cur)
        row.addStretch(1)
        v.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Пошук за кодом або назвою"))
        self.search.textChanged.connect(self._filter)
        self.lst = QListWidget()
        self.lst.itemDoubleClicked.connect(lambda _i: self.accept())
        self._stock: list[dict] = []
        for c in catalog:
            if np.abs(used_labs - np.asarray(c["lab"], np.float32)).sum(1).min() < 0.01:
                continue                                   # такий колір уже є в картині (його треба зливати, а не додавати)
            self._stock.append(c)
            it = QListWidgetItem(_swatch(c["hex"]), f'{c["code"]}  {c.get("name", "")}'.strip())
            it.setData(0x100, len(self._stock) - 1)
            self.lst.addItem(it)
        if catalog:
            v.addWidget(QLabel(tr("Фарби зі складу:")))
            v.addWidget(self.search)
            v.addWidget(self.lst, 1)
        else:
            v.addWidget(QLabel(tr("Каталог фарб не задано: оберіть власний колір.")))
            self.search.hide()
            self.lst.hide()
        self.btn_custom = QPushButton(tr("Власний колір…"))
        self.btn_custom.clicked.connect(self._custom)
        v.addWidget(self.btn_custom)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._current_hex = current_hex

    def _filter(self, text: str) -> None:
        t = text.strip().lower()
        for i in range(self.lst.count()):
            self.lst.item(i).setHidden(bool(t) and t not in self.lst.item(i).text().lower())

    def _custom(self) -> None:
        c = QColorDialog.getColor(QColor(self._current_hex), self, tr("Власний колір"))
        if c.isValid():
            self.result_lab = hex_to_lab(c.name())
            super().accept()

    def accept(self) -> None:
        it = self.lst.currentItem()
        if it is not None and not it.isHidden():
            self.result_lab = list(map(float, self._stock[it.data(0x100)]["lab"]))
            super().accept()
