"""Редактор каталогу фарб (палітри) без ручного редагування JSON: таблиця, вибір кольору, імпорт, збереження."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..i18n import tr
from ..palette.catalog import CatalogError, catalog_to_json, load_catalog, paint_hex, save_catalog

COLS = ["", "Код", "Назва", "HEX", "Пігмент (CI)", "Сила"]
SWATCH, CODE, NAME, HEX, PIG, STR = range(6)
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _norm_hex(text: str) -> str | None:
    m = _HEX.match(text.strip())
    return "#" + m.group(1).upper() if m else None


class PaletteEditor(QDialog):
    """Після «Застосувати» сигнал applied(path) --- файл каталогу збережено й готовий до завантаження."""
    applied = Signal(str)

    def __init__(self, paints: list[dict] | None = None, name: str = "", path: str = "", start_dir: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Редактор палітри"))
        self.resize(820, 560)
        self.path = path
        self.start_dir = start_dir
        self._loading = False
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Назва набору:")))
        self.ed_name = QLineEdit(name or tr("Мій набір фарб"))
        top.addWidget(self.ed_name, 1)
        lay.addLayout(top)
        self.tbl = QTableWidget(0, len(COLS))
        self.tbl.setHorizontalHeaderLabels([tr(c) for c in COLS])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl.setColumnWidth(SWATCH, 36)
        self.tbl.setColumnWidth(CODE, 90)
        self.tbl.setColumnWidth(NAME, 220)
        self.tbl.setColumnWidth(HEX, 90)
        self.tbl.setColumnWidth(PIG, 150)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.itemChanged.connect(self._changed)
        self.tbl.itemDoubleClicked.connect(lambda it: self.pick_color() if it.column() == SWATCH else None)
        self.tbl.horizontalHeaderItem(PIG).setToolTip(tr("Індекс пігменту Colour Index, наприклад PW6 або PB29 + PY150"))
        self.horizontalHeaderItem_strength = self.tbl.horizontalHeaderItem(STR)
        self.horizontalHeaderItem_strength.setToolTip(tr("Лише для змішування: 1 = середня, більше = сильніше фарбує суміш (0,1..10)"))
        lay.addWidget(self.tbl, 1)
        self.lbl_info = QLabel()
        lay.addWidget(self.lbl_info)
        row = QHBoxLayout()
        for text, fn in ((tr("Додати"), self.add_row), (tr("Дублювати"), self.dup_row), (tr("Видалити"), self.del_rows),
                         (tr("Колір…"), self.pick_color), (tr("Відкрити файл…"), self.open_file)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        b = QPushButton(tr("Зберегти як…"))
        b.clicked.connect(lambda _=False: self.save_as())
        self.btn_apply = QPushButton(tr("Застосувати до програми"))
        self.btn_apply.setToolTip(tr("Зберігає файл (якщо ще не збережено) і підключає палітру як каталог"))
        self.btn_apply.clicked.connect(lambda _=False: self.apply())
        bc = QPushButton(tr("Закрити"))
        bc.clicked.connect(self.reject)
        row2.addWidget(b)
        row2.addStretch(1)
        row2.addWidget(self.btn_apply)
        row2.addWidget(bc)
        lay.addLayout(row2)
        self.set_paints(paints or [])
        if not paints:
            self.add_row()

    # ---------------------------------------------------------------- дані
    def set_paints(self, paints: list[dict]) -> None:
        self._loading = True
        self.tbl.setRowCount(0)
        for p in paints:
            self._append(p.get("code", ""), p.get("name", ""), paint_hex(p),
                         " + ".join(p.get("pigments") or []) if not isinstance(p.get("pigments"), str) else p["pigments"],
                         p.get("strength", 1.0))
        self._loading = False
        self._refresh_all()

    def _append(self, code="", name="", hexs="#808080", pig="", strength=1.0) -> int:
        r = self.tbl.rowCount()
        self._loading = True
        self.tbl.insertRow(r)
        sw = QTableWidgetItem()
        sw.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.tbl.setItem(r, SWATCH, sw)
        for c, v in ((CODE, code), (NAME, name), (HEX, hexs), (PIG, pig), (STR, "" if strength in (None, 1, 1.0) else str(strength))):
            self.tbl.setItem(r, c, QTableWidgetItem(str(v)))
        self._loading = False
        self._refresh_row(r)
        return r

    def rows(self) -> list[dict]:
        out = []
        for r in range(self.tbl.rowCount()):
            g = lambda c: (self.tbl.item(r, c).text() if self.tbl.item(r, c) else "").strip()   # noqa: E731
            out.append({"code": g(CODE), "name": g(NAME), "hex": g(HEX), "pigments": g(PIG), "strength": g(STR) or None})
        return out

    def validate(self) -> tuple[dict | None, str]:
        """(JSON-словник, "") або (None, текст помилки українською)."""
        try:
            return catalog_to_json(self.ed_name.text().strip(), self.rows()), ""
        except CatalogError as e:
            return None, str(e)

    # ---------------------------------------------------------------- вигляд
    def _refresh_row(self, r: int) -> None:
        item = self.tbl.item(r, HEX)
        hx = _norm_hex(item.text()) if item else None
        sw = self.tbl.item(r, SWATCH)
        if sw:
            sw.setBackground(QBrush(QColor(hx) if hx else QColor("#ffffff")))
        if item:
            item.setForeground(QBrush(QColor("#000000") if hx else QColor("#c00000")))

    def _refresh_all(self) -> None:
        for r in range(self.tbl.rowCount()):
            self._refresh_row(r)
        self._info()

    def _info(self) -> None:
        data, err = self.validate()
        n = self.tbl.rowCount()
        self.lbl_info.setText(tr(f"Фарб: {n}.") + ("  " + tr("Готово до збереження.") if not err else "  ⚠ " + tr(err)))
        self.lbl_info.setStyleSheet("" if not err else "color: #b00020;")

    def _changed(self, item) -> None:
        if self._loading:
            return
        if item.column() == HEX:
            h = _norm_hex(item.text())
            if h and item.text() != h:
                self._loading = True
                item.setText(h)
                self._loading = False
        self._refresh_row(item.row())
        self._info()

    # ---------------------------------------------------------------- дії
    def add_row(self) -> None:
        used = {r["code"] for r in self.rows()}
        i = len(used) + 1
        while f"P-{i:02d}" in used:
            i += 1
        r = self._append(f"P-{i:02d}")
        self.tbl.setCurrentCell(r, CODE)
        self.tbl.editItem(self.tbl.item(r, CODE))
        self._info()

    def dup_row(self) -> None:
        r = self.tbl.currentRow()
        if r < 0:
            return
        d = self.rows()[r]
        used = {x["code"] for x in self.rows()}
        code, k = d["code"] + "-2", 2
        while code in used:
            k += 1
            code = f"{d['code']}-{k}"
        self._append(code, d["name"], d["hex"], d["pigments"], d["strength"] or 1.0)
        self._info()

    def del_rows(self) -> None:
        rows = {i.row() for i in self.tbl.selectedIndexes()} or ({self.tbl.currentRow()} if self.tbl.currentRow() >= 0 else set())
        for r in sorted(rows, reverse=True):
            self.tbl.removeRow(r)
        self._info()

    def pick_color(self) -> None:
        r = self.tbl.currentRow()
        if r < 0:
            return
        cur = _norm_hex(self.tbl.item(r, HEX).text()) or "#808080"
        c = QColorDialog.getColor(QColor(cur), self, tr("Колір фарби"))
        if c.isValid():
            self.tbl.item(r, HEX).setText(c.name().upper())

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Каталог фарб"), self.start_dir, "JSON (*.json)")
        if not path:
            return
        try:
            paints = load_catalog(path)
        except (CatalogError, OSError) as e:
            QMessageBox.warning(self, tr("Помилка в каталозі"), tr(str(e)))
            return
        self.set_paints(paints)
        self.path = path
        self.ed_name.setText(Path(path).stem)
        self._info()

    def save_as(self) -> bool:
        data, err = self.validate()
        if data is None:
            QMessageBox.warning(self, tr("Помилка в каталозі"), tr(err))
            return False
        path, _ = QFileDialog.getSaveFileName(self, tr("Зберегти палітру"), self.path or str(Path(self.start_dir or ".") / "palette.json"),
                                              "JSON (*.json)")
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            save_catalog(path, self.ed_name.text().strip(), self.rows())
        except OSError as e:
            QMessageBox.critical(self, tr("Помилка"), str(e))
            return False
        self.path = path
        return True

    def apply(self) -> None:
        data, err = self.validate()
        if data is None:
            QMessageBox.warning(self, tr("Помилка в каталозі"), tr(err))
            return
        if not self.path and not self.save_as():
            return
        try:
            save_catalog(self.path, self.ed_name.text().strip(), self.rows())     # актуальний стан у файл
        except OSError as e:
            QMessageBox.critical(self, tr("Помилка"), str(e))
            return
        self.applied.emit(self.path)
        self.accept()
