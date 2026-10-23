"""Діалог пакетної обробки: папка з фото або CSV-маніфест -> замовлення в одну вихідну папку."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..batch import build_items, exit_code, run_batch, write_report
from ..settings import Settings

STATUS_TEXT = {"pending": "очікує", "ok": "готово", "blocked": "заблоковано", "error": "помилка",
               "skipped": "пропущено", "cancelled": "перервано"}
STATUS_COLOR = {"ok": "#2e7d32", "blocked": "#e68900", "error": "#d32f2f", "skipped": "#6b6b6b", "cancelled": "#6b6b6b"}
COLS = ["Файл", "Замовлення", "Статус", "Ділянок", "Кольорів", "Ємностей", "Примітка"]


class BatchJob(QThread):
    progressed = Signal(int, int, object)
    finishedRows = Signal(object)
    failed = Signal(str)

    def __init__(self, items, out, jobs, compare, skip, parent=None):
        super().__init__(parent)
        self.items, self.out, self.jobs, self.compare, self.skip = items, out, jobs, compare, skip
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self):
        try:
            rows = run_batch(self.items, self.out, self.jobs, self.compare, self.skip,
                             progress=lambda d, t, r: self.progressed.emit(d, t, r), cancel=lambda: self._cancel)
            self.finishedRows.emit(rows)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class BatchDialog(QDialog):
    def __init__(self, base: Settings, prefs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Пакетна обробка")
        self.resize(900, 600)
        self.base = dataclasses.replace(base, zones=[])      # зони стосуються конкретного фото: беруться з <імʼя>.zones.json
        self.prefs = prefs
        self.source: str | None = None
        self.items = []
        self.job: BatchJob | None = None
        self.rows: list[dict] = []

        v = QVBoxLayout(self)
        top = QFormLayout()
        row = QHBoxLayout()
        self.lbl_src = QLabel("не вибрано")
        b1, b2 = QPushButton("Папка з фото…"), QPushButton("Маніфест CSV…")
        b1.clicked.connect(self.pick_folder)
        b2.clicked.connect(self.pick_manifest)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addWidget(self.lbl_src, 1)
        top.addRow("Джерело", row)
        row = QHBoxLayout()
        self.lbl_out = QLabel(prefs.get("last_save_dir") or "не вибрано")
        b3 = QPushButton("Куди зберегти…")
        b3.clicked.connect(self.pick_out)
        row.addWidget(b3)
        row.addWidget(self.lbl_out, 1)
        top.addRow("Результат", row)
        self.cmb_num = QComboBox()
        self.cmb_num.addItem("за імʼям файлу", "name")
        self.cmb_num.addItem("послідовні (000001, 000002…)", "sequential")
        self.ed_prefix = QLineEdit()
        self.sp_start = QSpinBox(minimum=1, maximum=999999, value=1)
        r2 = QHBoxLayout()
        for w in (self.cmb_num, QLabel("префікс"), self.ed_prefix, QLabel("початок"), self.sp_start):
            r2.addWidget(w)
        top.addRow("Номери замовлень", r2)
        for sig in (self.cmb_num.currentIndexChanged, self.ed_prefix.editingFinished, self.sp_start.valueChanged):
            sig.connect(lambda *_: self.refresh_items() if self.source and not self.job else None)
        self.cb_compare = QCheckBox("для кожного фото підбирати найкращий варіант (повільніше: до 9 прогонів на фото)")
        self.cb_skip = QCheckBox("пропускати замовлення, які вже готові")
        self.cb_skip.setChecked(True)
        self.sp_jobs = QSpinBox(minimum=1, maximum=16, value=2)
        self.sp_jobs.setToolTip("Скільки фото обробляти одночасно (кожне --- в окремому процесі)")
        top.addRow(self.cb_compare)
        top.addRow(self.cb_skip)
        top.addRow("Процесів", self.sp_jobs)
        v.addLayout(top)
        hint = QLabel("Налаштування (режим, кольори, розмір, фарби, норма покриття) беруться з головного вікна. "
                      "Зони: файл <імʼя фото>.zones.json поруч із фото. У маніфесті можна задати для кожного фото "
                      "order, name, width_mm, height_mm, mode, colors, zones.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        v.addWidget(hint)

        self.tbl = QTableWidget(0, len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.tbl, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.lbl_status = QLabel("")
        v.addWidget(self.progress)
        v.addWidget(self.lbl_status)
        btns = QHBoxLayout()
        self.btn_start = QPushButton("Почати")
        self.btn_start.setStyleSheet("font-weight: bold;")
        self.btn_start.clicked.connect(self.start)
        self.btn_cancel = QPushButton("Перервати")
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_close = QPushButton("Закрити")
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_start, self.btn_cancel, self.btn_close):
            btns.addWidget(b)
        v.addLayout(btns)
        self._update_buttons()

    # ---- вибір джерела
    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Папка з фото", self.prefs.get("last_photo_dir"))
        if d:
            self.set_source(d)

    def pick_manifest(self):
        f, _ = QFileDialog.getOpenFileName(self, "Маніфест", self.prefs.get("last_photo_dir"), "CSV (*.csv *.txt)")
        if f:
            self.set_source(f)

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Куди зберегти замовлення", self.prefs.get("last_save_dir"))
        if d:
            self.set_out(d)

    def set_out(self, d: str) -> None:
        self.lbl_out.setText(d)
        self._update_buttons()

    def set_source(self, path: str) -> None:
        self.source = path
        self.lbl_src.setText(path)
        self.refresh_items()

    def refresh_items(self) -> None:
        try:
            self.items = build_items(self.source, self.base, self.cmb_num.currentData(), self.sp_start.value(),
                                     self.ed_prefix.text())
        except ValueError as e:
            QMessageBox.warning(self, "Пакетна обробка", str(e))
            self.items = []
        self.rows = []
        self.tbl.setRowCount(len(self.items))
        for i, it in enumerate(self.items):
            self._set_row(i, {"file": it.photo.name, "order": it.order, "status": "error" if it.error else "pending",
                              "regions": "", "colors": "", "containers": "", "message": it.error})
        self.lbl_status.setText(f"Фото: {len(self.items)}" + (f", з помилками: {sum(1 for i in self.items if i.error)}"
                                                               if any(i.error for i in self.items) else ""))
        self._update_buttons()

    def _set_row(self, i: int, r: dict) -> None:
        vals = [r["file"], r["order"], STATUS_TEXT.get(r["status"], r["status"]), r.get("regions", ""),
                r.get("colors", ""), r.get("containers", ""), r.get("message", "")]
        for j, v in enumerate(vals):
            it = QTableWidgetItem(str(v))
            if j == 2 and r["status"] in STATUS_COLOR:
                it.setForeground(QBrush(QColor(STATUS_COLOR[r["status"]])))
            self.tbl.setItem(i, j, it)

    # ---- запуск
    def _update_buttons(self) -> None:
        running = self.job is not None
        ready = bool(self.items) and self.lbl_out.text() not in ("", "не вибрано") and not running
        self.btn_start.setEnabled(ready)
        self.btn_cancel.setEnabled(running)
        self.btn_close.setEnabled(not running)

    def start(self) -> None:
        if self.job or not self.items:
            return
        self.refresh_items() if self.source else None       # номери могли змінитися
        out = self.lbl_out.text()
        self.progress.setRange(0, len(self.items))
        self.progress.setValue(0)
        self.job = BatchJob(self.items, out, self.sp_jobs.value(), self.cb_compare.isChecked(),
                            self.cb_skip.isChecked(), self)
        self.job.progressed.connect(self._progressed)
        self.job.finishedRows.connect(self._done)
        self.job.failed.connect(self._failed)
        self.job.finished.connect(self._job_finished)
        self.prefs.set("last_save_dir", out)
        self.lbl_status.setText("Обробка…")
        self.job.start()
        self._update_buttons()

    def cancel(self) -> None:
        if self.job:
            self.job.cancel()
            self.lbl_status.setText("Переривання: поточні фото буде дооброблено…")

    def _progressed(self, done: int, total: int, row: dict) -> None:
        self.progress.setValue(done)
        for i, it in enumerate(self.items):
            if it.photo.name == row["file"] and it.order == row["order"]:
                self._set_row(i, row)
                break
        self.lbl_status.setText(f"{done} з {total}")

    def _done(self, rows: list[dict]) -> None:
        self.rows = rows
        for i, r in enumerate(rows):
            self._set_row(i, r)
        rep = write_report(rows, self.lbl_out.text(), self.base)
        ok = sum(r["status"] == "ok" for r in rows)
        bad = sum(r["status"] in ("error", "blocked") for r in rows)
        self.lbl_status.setText(f"Готово: {ok} з {len(rows)}" + (f", потребують уваги: {bad}" if bad else "")
                                + f". Звіт: {rep}")

    def _failed(self, msg: str) -> None:
        QMessageBox.critical(self, "Пакетна обробка", msg)

    def _job_finished(self) -> None:
        self.job = None
        self._update_buttons()

    def closeEvent(self, e):
        if self.job:
            e.ignore()
            return
        super().closeEvent(e)

    def exit_code(self) -> int:
        return exit_code(self.rows) if self.rows else 0
