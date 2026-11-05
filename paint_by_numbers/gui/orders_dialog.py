"""Пошук замовлень у папці за номером чи назвою; відкриття й безповоротне видалення (ТЗ 15.2, 20)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..i18n import tr
from ..orders import OrderError, delete_order, find_orders


class OrdersDialog(QDialog):
    openRequested = Signal(str)

    def __init__(self, root: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Пошук замовлень"))
        self.resize(760, 420)
        self.root = root
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.lbl_root = QLabel()
        b = QPushButton(tr("Обрати папку…"))
        b.clicked.connect(self.choose_root)
        top.addWidget(self.lbl_root, 1)
        top.addWidget(b)
        lay.addLayout(top)
        self.ed_q = QLineEdit(placeholderText=tr("Пошук за номером або назвою"))
        self.ed_q.textChanged.connect(self.refresh)
        lay.addWidget(self.ed_q)
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels([tr("Номер"), tr("Назва"), tr("Створено"), tr("Папка")])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.doubleClicked.connect(lambda _=None: self.open_selected())
        lay.addWidget(self.tbl, 1)
        row = QHBoxLayout()
        self.btn_open = QPushButton(tr("Відкрити"))
        self.btn_open.clicked.connect(self.open_selected)
        self.btn_del = QPushButton(tr("Видалити замовлення…"))
        self.btn_del.clicked.connect(self.delete_selected)
        bc = QPushButton(tr("Закрити"))
        bc.clicked.connect(self.accept)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_del)
        row.addStretch(1)
        row.addWidget(bc)
        lay.addLayout(row)
        self.refresh()

    def choose_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Папка із замовленнями"), self.root)
        if d:
            self.root = d
            self.refresh()

    def refresh(self) -> None:
        self.lbl_root.setText(self.root or tr("Папку не обрано"))
        items = find_orders(self.root, self.ed_q.text()) if self.root and Path(self.root).is_dir() else []
        self.tbl.setRowCount(len(items))
        for r, i in enumerate(items):
            for c, v in enumerate((i["order_number"], i["project_name"], i["created"][:16].replace("T", " "), i["folder"])):
                self.tbl.setItem(r, c, QTableWidgetItem(v))
        self.btn_open.setEnabled(bool(items))
        self.btn_del.setEnabled(bool(items))

    def selected(self) -> str | None:
        r = self.tbl.currentRow()
        it = self.tbl.item(r, 3) if r >= 0 else None
        return it.text() if it else None

    def open_selected(self) -> None:
        f = self.selected()
        if f:
            self.openRequested.emit(f)
            self.accept()

    def delete_selected(self) -> None:
        f = self.selected()
        if not f:
            return
        ans = QMessageBox.warning(
            self, tr("Видалити замовлення"),
            tr(f"Буде безповоротно видалено всю папку замовлення разом із фото клієнта, проєктом і пакетом:\n{f}\n\nПродовжити?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_order(f)
        except (OrderError, OSError) as e:
            QMessageBox.critical(self, tr("Помилка"), tr(str(e)) if isinstance(e, OrderError) else str(e))
        self.refresh()
