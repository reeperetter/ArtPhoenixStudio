"""Захист від випадкової зміни значень колесом миші.

Без цього при гортанні панелі колесом курсор, що проходить над полем з числом чи списком, «чіпляє» його, і значення
змінюється само. Тут поле змінюється колесом лише тоді, коли воно в фокусі (на нього явно клацнули); інакше колесо
передається прокрутці панелі, а клацання/Tab, як і раніше, працюють."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QComboBox, QWidget

GUARDED = (QAbstractSpinBox, QComboBox)


class WheelGuard(QObject):
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel or not isinstance(obj, GUARDED) or obj.hasFocus():
            return False
        w = obj.parentWidget()
        while w is not None and not isinstance(w, QAbstractScrollArea):
            w = w.parentWidget()
        if w is not None:                                   # передаємо колесо прокрутці панелі
            QCoreApplication.sendEvent(w.viewport(), event)
        else:
            event.ignore()
        return True


def install(root: QWidget) -> WheelGuard:
    """Захищає всі поля з числами та списки всередині root (виклик після побудови інтерфейсу)."""
    guard = WheelGuard(root)
    for cls in GUARDED:
        for w in root.findChildren(cls):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)    # колесо більше не віддає полю фокус
            w.installEventFilter(guard)
    return guard
