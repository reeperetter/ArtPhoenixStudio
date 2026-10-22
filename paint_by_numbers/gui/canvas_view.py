"""Перегляд зображення з масштабуванням і малювання зон пріоритету мишею."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QImage, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView)

from . import zone_utils as zu


def bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(bgr[..., ::-1])
    h, w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())


class ImageView(QGraphicsView):
    """Зображення з масштабуванням коліщатком і перетягуванням."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._pix)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#2b2b2b")))
        self.setRenderHints(self.renderHints())
        self._has_image = False
        self.img_w = self.img_h = 0

    def set_image(self, bgr: np.ndarray | None, keep_view: bool = False) -> None:
        if bgr is None:
            self._pix.setPixmap(QPixmap())
            self._has_image = False
            return
        first = not self._has_image
        self.img_h, self.img_w = bgr.shape[:2]
        self._pix.setPixmap(bgr_to_pixmap(bgr))
        self._scene.setSceneRect(QRectF(0, 0, self.img_w, self.img_h))
        self._has_image = True
        if first or not keep_view:
            self.fit()

    def fit(self) -> None:
        if self._has_image:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def resizeEvent(self, e):
        super().resizeEvent(e)


class ZoneCanvas(ImageView):
    """Фото на полотні; зони малюються миші. Координати зон нормовані (0..1) відносно полотна."""
    zoneDrawn = Signal(dict)
    zoneClicked = Signal(int)

    TOOLS = ("pan", "select", "rect", "ellipse", "polygon")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tool = "pan"
        self.zones: list[dict] = []
        self.selected = -1
        self.default_weight = 2.0
        self._items: list = []
        self._start: QPointF | None = None
        self._rubber: QGraphicsPathItem | None = None
        self._poly: list[tuple[float, float]] = []
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ---- інструменти
    def set_tool(self, tool: str) -> None:
        self._cancel_drawing()
        self.tool = tool
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if tool == "pan" else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(QCursor(Qt.CursorShape.OpenHandCursor if tool == "pan"
                                          else Qt.CursorShape.ArrowCursor if tool == "select"
                                          else Qt.CursorShape.CrossCursor))

    def _cancel_drawing(self) -> None:
        if self._rubber is not None:
            self._scene.removeItem(self._rubber)
            self._rubber = None
        self._poly = []
        self._start = None

    # ---- відображення зон
    def set_zones(self, zones: list[dict], selected: int = -1) -> None:
        self.zones, self.selected = zones, selected
        for it in self._items:
            self._scene.removeItem(it)
        self._items = []
        if not self._has_image:
            return
        for i, z in enumerate(zones):
            pts = zu.zone_outline(z, self.img_w, self.img_h)
            path = QPainterPath()
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts] + [QPointF(*pts[0])]))
            it = QGraphicsPathItem(path)
            sel = i == selected
            pen = QPen(QColor("#ffd400") if sel else QColor("#ff3b30"), 3 if sel else 2)
            pen.setCosmetic(True)
            it.setPen(pen)
            alpha = int(40 + 25 * min(float(z.get("weight", 2.0)), 5.0))
            it.setBrush(QBrush(QColor(255, 59, 48, alpha)))
            it.setZValue(10)
            self._scene.addItem(it)
            txt = QGraphicsSimpleTextItem(f'{z.get("name", "")} ({float(z.get("weight", 2.0)):g})', it)
            txt.setBrush(QBrush(QColor("white")))
            txt.setFlag(txt.GraphicsItemFlag.ItemIgnoresTransformations)
            txt.setPos(min(p[0] for p in pts), min(p[1] for p in pts))
            self._items += [it]

    # ---- миша
    def mousePressEvent(self, e):
        if self.tool == "pan" or not self._has_image:
            return super().mousePressEvent(e)
        self.setFocus()
        p = self.mapToScene(e.position().toPoint())
        if self.tool == "select":
            if e.button() == Qt.MouseButton.LeftButton:
                hit = [i for i, z in enumerate(self.zones)
                       if zu.point_in_zone(z, p.x(), p.y(), self.img_w, self.img_h)]
                self.zoneClicked.emit(min(hit, key=lambda i: zu.zone_area(self.zones[i])) if hit else -1)
            return
        if self.tool in ("rect", "ellipse") and e.button() == Qt.MouseButton.LeftButton:
            self._start = p
            self._rubber = QGraphicsPathItem()
            pen = QPen(QColor("#ffd400"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._rubber.setPen(pen)
            self._rubber.setZValue(20)
            self._scene.addItem(self._rubber)
        elif self.tool == "polygon":
            if e.button() == Qt.MouseButton.LeftButton:
                self._poly.append((p.x(), p.y()))
                self._draw_poly(p)
            elif e.button() == Qt.MouseButton.RightButton:
                self._finish_polygon()

    def mouseMoveEvent(self, e):
        if self.tool == "pan" or not self._has_image:
            return super().mouseMoveEvent(e)
        p = self.mapToScene(e.position().toPoint())
        if self._rubber is not None and self._start is not None and self.tool in ("rect", "ellipse"):
            r = QRectF(self._start, p).normalized()
            path = QPainterPath()
            (path.addEllipse if self.tool == "ellipse" else path.addRect)(r)
            self._rubber.setPath(path)
        elif self.tool == "polygon" and self._poly:
            self._draw_poly(p)

    def mouseReleaseEvent(self, e):
        if self.tool == "pan" or not self._has_image:
            return super().mouseReleaseEvent(e)
        if self._start is not None and self.tool in ("rect", "ellipse"):
            p = self.mapToScene(e.position().toPoint())
            a, b = (self._start.x(), self._start.y()), (p.x(), p.y())
            self._cancel_drawing()
            fn = zu.ellipse_zone if self.tool == "ellipse" else zu.rect_zone
            z = fn(a, b, self.img_w, self.img_h, "", self.default_weight)
            if z:
                self.zoneDrawn.emit(z)

    def mouseDoubleClickEvent(self, e):
        if self.tool == "polygon" and self._poly:
            self._poly = self._poly[:-1] if len(self._poly) > 1 else self._poly   # дубль від першого кліку
            self._finish_polygon()
        else:
            super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if self.tool == "polygon" and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish_polygon()
        elif e.key() == Qt.Key.Key_Escape:
            self._cancel_drawing()
        else:
            super().keyPressEvent(e)

    def _draw_poly(self, cursor: QPointF) -> None:
        if self._rubber is None:
            self._rubber = QGraphicsPathItem()
            pen = QPen(QColor("#ffd400"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._rubber.setPen(pen)
            self._rubber.setZValue(20)
            self._scene.addItem(self._rubber)
        path = QPainterPath(QPointF(*self._poly[0]))
        for x, y in self._poly[1:]:
            path.lineTo(x, y)
        path.lineTo(cursor)
        self._rubber.setPath(path)

    def _finish_polygon(self) -> None:
        pts = list(self._poly)
        self._cancel_drawing()
        z = zu.polygon_zone(pts, self.img_w, self.img_h, "", self.default_weight)
        if z:
            self.zoneDrawn.emit(z)
