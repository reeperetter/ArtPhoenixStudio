"""Вкладка ручного редагування ділянок: змінити колір ділянки, злити із сусідньою, зафарбувати полігон."""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QIcon, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGraphicsPathItem, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from .canvas_view import ImageView

HINTS = {
    "pan": "Рука: перетягуйте зображення, колесо --- масштаб, подвійний клік або 0 --- вмістити.",
    "recolor": "Клік по ділянці --- вона отримає вибраний колір (сусідні ділянки того ж кольору зіллються).",
    "merge": "Клік по ділянці, яку треба прибрати, потім клік по сусідній --- перша зіллється з другою.",
    "polygon": "Клік --- додати точку полігона; правий клік, Enter або подвійний клік --- завершити; Esc --- скасувати. "
               "Область отримає вибраний колір.",
}


class RegionView(ImageView):
    picked = Signal(float, float)            # координати в пікселях розбиття
    polygonDone = Signal(list)
    escaped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tool = "pan"
        self.scale_px = 1.0                  # пікселів зображення на піксель розбиття
        self._poly: list[tuple[float, float]] = []
        self._poly_item: QGraphicsPathItem | None = None
        self._hl: list[QGraphicsPathItem] = []
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _pan_mode(self) -> bool:
        return self.tool == "pan"

    def set_tool(self, tool: str) -> None:
        self.cancel_polygon()
        self.tool = tool
        self.viewport().setCursor(QCursor(Qt.CursorShape.OpenHandCursor if tool == "pan" else Qt.CursorShape.CrossCursor))

    def _label_xy(self, e) -> tuple[float, float]:
        p = self.mapToScene(e.position().toPoint())
        return p.x() / self.scale_px, p.y() / self.scale_px

    def mousePressEvent(self, e):
        if self._has_image and self.tool != "pan" and e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            if self.tool == "polygon":
                if e.button() == Qt.MouseButton.RightButton:
                    self.finish_polygon()
                else:
                    self._poly.append(self._label_xy(e))
                    self._draw_poly()
            elif e.button() == Qt.MouseButton.LeftButton:
                self.picked.emit(*self._label_xy(e))
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.tool == "polygon" and e.button() == Qt.MouseButton.LeftButton:
            if len(self._poly) > 1:
                self._poly.pop()                 # перший клік подвійного кліку вже додав точку, другий дублює її
            self.finish_polygon()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if self.tool == "polygon" and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_polygon()
        elif e.key() == Qt.Key.Key_Escape:
            self.cancel_polygon()
            self.escaped.emit()
        else:
            super().keyPressEvent(e)

    def finish_polygon(self) -> None:
        pts, self._poly = self._poly, []
        self._clear_poly()
        if len(pts) >= 3:
            self.polygonDone.emit(pts)

    def cancel_polygon(self) -> None:
        self._poly = []
        self._clear_poly()

    def _clear_poly(self) -> None:
        if self._poly_item is not None:
            self._scene.removeItem(self._poly_item)
            self._poly_item = None

    def _draw_poly(self) -> None:
        self._clear_poly()
        path = QPainterPath(QPointF(self._poly[0][0] * self.scale_px, self._poly[0][1] * self.scale_px))
        for x, y in self._poly[1:]:
            path.lineTo(x * self.scale_px, y * self.scale_px)
        pen = QPen(QColor("#ffcc00"), 2)
        pen.setCosmetic(True)
        self._poly_item = self._scene.addPath(path, pen)
        self._poly_item.setZValue(10)

    def set_highlight(self, mask: np.ndarray | None) -> None:
        for it in self._hl:
            self._scene.removeItem(it)
        self._hl = []
        if mask is None or not mask.any():
            return
        cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        pen = QPen(QColor("#ff2d95"), 3)
        pen.setCosmetic(True)
        for c in cs:
            pts = c.reshape(-1, 2).astype(float) * self.scale_px
            path = QPainterPath(QPointF(*pts[0]))
            for x, y in pts[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
            it = self._scene.addPath(path, pen, QBrush(QColor(255, 45, 149, 60)))
            it.setZValue(9)
            self._hl.append(it)


def _swatch(hex_color: str) -> QIcon:
    pm = QPixmap(16, 16)
    pm.fill(QColor(hex_color))
    return QIcon(pm)


class RegionEditPanel(QWidget):
    """Панель інструментів + зображення. Власних обчислень немає: сигнали обробляє головне вікно."""
    recolorRequested = Signal(float, float, int)      # x, y, індекс кольору в списку choices
    mergeRequested = Signal(float, float, float, float)
    polygonRequested = Signal(list, int)
    undoRequested = Signal()
    redoRequested = Signal()
    toolChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.tool_buttons: dict[str, QPushButton] = {}
        for key, text in (("pan", "Рука"), ("recolor", "Змінити колір"), ("merge", "Злити із сусідньою"),
                          ("polygon", "Зафарбувати полігон")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_tool(k))
            self.group.addButton(b)
            self.tool_buttons[key] = b
            bar.addWidget(b)
        self.tool_buttons["pan"].setChecked(True)
        bar.addWidget(QLabel("Колір:"))
        self.cmb = QComboBox()
        self.cmb.setMinimumWidth(220)
        bar.addWidget(self.cmb)
        self.btn_undo = QPushButton("↶ Скасувати правку")
        self.btn_redo = QPushButton("↷ Повторити")
        self.btn_undo.clicked.connect(self.undoRequested)
        self.btn_redo.clicked.connect(self.redoRequested)
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.btn_redo)
        bar.addStretch(1)
        v.addLayout(bar)
        self.lbl = QLabel(HINTS["pan"])
        self.lbl.setWordWrap(True)
        v.addWidget(self.lbl)
        self.view = RegionView()
        v.addWidget(self.view, 1)
        self.view.picked.connect(self._picked)
        self.view.polygonDone.connect(lambda pts: self.polygonRequested.emit(pts, self.cmb.currentIndex()))
        self.view.escaped.connect(lambda: self.set_tool(self.tool))
        self._first: tuple[float, float] | None = None
        self.tool = "pan"
        self.setEnabled(False)

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._first = None
        self.view.set_highlight(None)
        self.view.set_tool(tool)
        self.tool_buttons[tool].setChecked(True)
        self.lbl.setText(HINTS[tool])
        self.toolChanged.emit(tool)

    def set_choices(self, items: list[tuple[str, str]], keep: int | None = None) -> None:
        """items: (підпис, hex)."""
        cur = self.cmb.currentIndex() if keep is None else keep
        self.cmb.blockSignals(True)
        self.cmb.clear()
        for text, hx in items:
            self.cmb.addItem(_swatch(hx), text)
        self.cmb.setCurrentIndex(min(max(cur, 0), len(items) - 1) if items else -1)
        self.cmb.blockSignals(False)

    def show_image(self, bgr: np.ndarray | None, label_w: int) -> None:
        if bgr is None:
            self.view.set_image(None)
            self.setEnabled(False)
            return
        self.view.scale_px = bgr.shape[1] / label_w
        self.view.set_image(bgr, keep_view=True)
        self.setEnabled(True)

    def set_undo_state(self, can_undo: bool, can_redo: bool) -> None:
        self.btn_undo.setEnabled(can_undo)
        self.btn_redo.setEnabled(can_redo)

    def _picked(self, x: float, y: float) -> None:
        if self.tool == "recolor":
            self.recolorRequested.emit(x, y, self.cmb.currentIndex())
        elif self.tool == "merge":
            if self._first is None:
                self._first = (x, y)
                self.lbl.setText("Ділянку вибрано (рожева). Тепер клікніть по сусідній ділянці, з якою її злити. Esc --- скасувати.")
                self.highlightRequested(x, y)
            else:
                (x0, y0), self._first = self._first, None
                self.view.set_highlight(None)
                self.lbl.setText(HINTS["merge"])
                self.mergeRequested.emit(x0, y0, x, y)

    highlightPoint = Signal(float, float)

    def highlightRequested(self, x: float, y: float) -> None:
        self.highlightPoint.emit(x, y)
