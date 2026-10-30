"""Групи лівої панелі, що згортаються клацанням по заголовку (щоб панель вміщалася по висоті)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QWidget

from ..i18n import tr


class CollapsibleGroup(QGroupBox):
    toggled_collapsed = Signal(bool)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._collapsed = False
        self._hidden_before: set[QWidget] = set()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Клацніть по заголовку, щоб згорнути або розгорнути"))
        self._refresh_title()

    def _refresh_title(self) -> None:
        self.setTitle(("▸ " if self._collapsed else "▾ ") + self._title)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, value: bool) -> None:
        if value == self._collapsed:
            return
        self._collapsed = value
        kids = self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if value:
            self._hidden_before = {w for w in kids if w.isHidden()}
            for w in kids:
                w.hide()
        else:
            for w in kids:
                if w not in self._hidden_before:
                    w.show()
        self._refresh_title()
        self.toggled_collapsed.emit(value)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() <= self.fontMetrics().height() + 10:
            self.set_collapsed(not self._collapsed)
            e.accept()
            return
        super().mousePressEvent(e)
