"""Головне вікно: фото -> зони пріоритету -> превʼю -> виробничий пакет. Усі обчислення --- це ті самі
класичні алгоритми, що й у командному рядку (без ШІ)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)

from ..compare import default_variants, select_best
from ..generate import run_pipeline
from ..export.package import build_package
from ..image_io.loader import load_image
from ..palette.catalog import CatalogError, load_catalog
from ..project import ProjectError, open_project
from ..pipeline.priority_zones import MAX_WEIGHT, ZoneError, load_zones_file, parse_zones
from ..settings import PRESETS, Settings
from .canvas_view import ImageView, ZoneCanvas
from .history import UndoStack
from .prefs import Prefs

MODE_NAMES = {"simple": "Простий", "balanced": "Збалансований", "detailed": "Деталізований"}
SEV_COLOR = {"critical": "#d32f2f", "warning": "#e68900", "info": "#6b6b6b"}


class Job(QThread):
    """Виконує довгу операцію поза потоком інтерфейсу."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except (ProjectError, ZoneError, CatalogError) as e:     # повідомлення вже зрозуміле оператору
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class MainWindow(QMainWindow):
    def __init__(self, prefs: Prefs | None = None):
        super().__init__()
        self.prefs = prefs or Prefs()
        self.setWindowTitle("Картини за номерами")
        self.resize(1400, 860)
        self.photo: str | None = None
        self.zones: list[dict] = []
        self.res = None
        self.job: Job | None = None
        self._pending_apply: int | None = None
        self.history = UndoStack(([], -1))
        self._restoring = False
        self._reload_timer = QTimer(self, singleShot=True, interval=400)
        self._reload_timer.timeout.connect(self._reload_canvas)
        self._build_ui()
        self._build_menu()
        self._load_prefs()
        self._update_buttons()
        self._update_undo_actions()

    # ------------------------------------------------------------------ побудова
    def _build_ui(self) -> None:
        split = QSplitter(self)
        self.setCentralWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)

        # 1. фото
        g = QGroupBox("1. Фото")
        f = QVBoxLayout(g)
        self.btn_open = QPushButton("Відкрити фото…")
        self.btn_open.clicked.connect(self.open_photo)
        self.btn_open_proj = QPushButton("Відкрити проєкт (папку замовлення)…")
        self.btn_open_proj.setToolTip("Повертає збережене замовлення без перерахунку: налаштування, зони, фарби й результат")
        self.btn_open_proj.clicked.connect(self.open_project_dialog)
        self.original_name: str | None = None
        self.lbl_photo = QLabel("файл не вибрано")
        self.lbl_photo.setWordWrap(True)
        f.addWidget(self.btn_open)
        f.addWidget(self.btn_open_proj)
        f.addWidget(self.lbl_photo)
        lv.addWidget(g)

        # 2. полотно і режим
        g = QGroupBox("2. Полотно і режим")
        f = QFormLayout(g)
        self.sp_w = QDoubleSpinBox(maximum=3000, minimum=50, value=300, suffix=" мм", decimals=0)
        self.cb_auto_h = QCheckBox("висота за пропорціями фото")
        self.cb_auto_h.setChecked(True)
        self.sp_h = QDoubleSpinBox(maximum=3000, minimum=50, value=400, suffix=" мм", decimals=0)
        self.sp_h.setEnabled(False)
        self.cb_auto_h.toggled.connect(lambda c: self.sp_h.setEnabled(not c))
        self.cmb_mode = QComboBox()
        for k in PRESETS:
            self.cmb_mode.addItem(MODE_NAMES[k], k)
        self.cmb_mode.setCurrentIndex(list(PRESETS).index("balanced"))
        self.cb_auto_colors = QCheckBox("кількість кольорів за режимом")
        self.cb_auto_colors.setChecked(True)
        self.sp_colors = QSpinBox(minimum=4, maximum=64, value=24)
        self.sp_colors.setEnabled(False)
        self.cb_auto_colors.toggled.connect(lambda c: self.sp_colors.setEnabled(not c))
        f.addRow("Ширина", self.sp_w)
        f.addRow(self.cb_auto_h)
        f.addRow("Висота", self.sp_h)
        f.addRow("Режим", self.cmb_mode)
        f.addRow(self.cb_auto_colors)
        f.addRow("Кольорів", self.sp_colors)
        lv.addWidget(g)
        for w in (self.sp_w, self.sp_h):
            w.valueChanged.connect(self._schedule_reload)
        self.cb_auto_h.toggled.connect(self._schedule_reload)

        # 3. фарби
        g = QGroupBox("3. Фарби (необовʼязково)")
        f = QFormLayout(g)
        row = QHBoxLayout()
        self.btn_cat = QPushButton("Каталог…")
        self.btn_cat.clicked.connect(self.load_catalog_file)
        self.btn_cat_clear = QPushButton("Скинути")
        self.btn_cat_clear.clicked.connect(self.clear_catalog)
        row.addWidget(self.btn_cat)
        row.addWidget(self.btn_cat_clear)
        self.catalog: list[dict] = []
        self.lbl_cat = QLabel("каталог не задано (коди P-001…)")
        self.sp_cov = QDoubleSpinBox(maximum=1e7, minimum=0, decimals=0, singleStep=500, suffix=" мм²")
        self.sp_cov.setSpecialValueText("не задано")
        self.sp_k = QDoubleSpinBox(minimum=1.0, maximum=10.0, value=1.3, singleStep=0.1, decimals=2)
        self.cb_cov_ok = QCheckBox("норму N підтверджено фізичними тестами")
        f.addRow(row)
        f.addRow(self.lbl_cat)
        f.addRow("Покриття N однієї ємності", self.sp_cov)
        f.addRow("Коефіцієнт запасу K", self.sp_k)
        f.addRow(self.cb_cov_ok)
        lv.addWidget(g)

        # 4. зони
        g = QGroupBox("4. Зони пріоритету")
        v = QVBoxLayout(g)
        tools = QHBoxLayout()
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        for key, text, tip in (("pan", "✋", "Рука: тягніть зображення (колесо миші --- масштаб, подвійний клік --- вмістити; середня кнопка рухає в будь-якому режимі)"),
                               ("select", "↖", "Вибір і редагування: клік --- вибрати; тягніть зону, щоб посунути, білі ручки --- змінити розмір (у багатокутника --- вершини); Delete --- видалити"),
                               ("rect", "▭", "Прямокутна зона"),
                               ("ellipse", "◯", "Еліптична зона"),
                               ("polygon", "⬠", "Багатокутник: клік --- точка; подвійний клік, Enter або права кнопка --- завершити")):
            b = QToolButton(text=text, checkable=True, toolTip=tip)
            b.setMinimumWidth(38)
            b.setProperty("tool", key)
            self.tool_group.addButton(b)
            tools.addWidget(b)
            if key == "pan":
                b.setChecked(True)
        self.tool_group.buttonClicked.connect(lambda b: self.canvas.set_tool(b.property("tool")))
        v.addLayout(tools)
        self.lst_zones = QListWidget()
        self.lst_zones.setMaximumHeight(120)
        self.lst_zones.currentRowChanged.connect(self._zone_selected)
        v.addWidget(self.lst_zones)
        zf = QFormLayout()
        self.ed_zname = QLineEdit()
        self.ed_zname.editingFinished.connect(self._zone_edited)
        self.sp_zw = QDoubleSpinBox(minimum=0.1, maximum=MAX_WEIGHT, value=2.0, singleStep=0.5, decimals=1)
        self.sp_zw.valueChanged.connect(self._zone_edited)
        self.sp_zw.setToolTip("0.1…5: що більше, то більше деталей у зоні (та більше ділянок без місця для номера)")
        zf.addRow("Назва", self.ed_zname)
        zf.addRow("Вага", self.sp_zw)
        v.addLayout(zf)
        zu_row = QHBoxLayout()
        self.btn_undo = QPushButton("↶ Відмінити")
        self.btn_undo.clicked.connect(self.undo_zones)
        self.btn_redo = QPushButton("↷ Повторити")
        self.btn_redo.clicked.connect(self.redo_zones)
        zu_row.addWidget(self.btn_undo)
        zu_row.addWidget(self.btn_redo)
        v.addLayout(zu_row)
        zb = QHBoxLayout()
        self.btn_zdel = QPushButton("Видалити")
        self.btn_zdel.clicked.connect(self.delete_zone)
        self.btn_zload = QPushButton("Із файлу…")
        self.btn_zload.clicked.connect(self.load_zones)
        self.btn_zsave = QPushButton("У файл…")
        self.btn_zsave.clicked.connect(self.save_zones)
        for b in (self.btn_zdel, self.btn_zload, self.btn_zsave):
            zb.addWidget(b)
        v.addLayout(zb)
        lv.addWidget(g)

        # 5. дії
        g = QGroupBox("5. Результат")
        v = QVBoxLayout(g)
        self.btn_gen = QPushButton("Створити превʼю")
        self.btn_gen.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_gen.clicked.connect(self.generate)
        self.btn_cmp = QPushButton("Підібрати найкращий варіант")
        self.btn_cmp.setToolTip("Перебирає режими й кількості кольорів (до 9 варіантів, кілька хвилин), "
                                "обирає найкращий за формулою з compare.py і будує його превʼю")
        self.btn_cmp.clicked.connect(self.compare_variants)
        v.addWidget(self.btn_cmp)
        f = QFormLayout()
        self.ed_order = QLineEdit("000001")
        self.ed_name = QLineEdit()
        f.addRow("Номер замовлення", self.ed_order)
        f.addRow("Назва проєкту", self.ed_name)
        self.btn_save = QPushButton("Зберегти пакет…")
        self.btn_save.clicked.connect(self.save_package)
        self.progress = QProgressBar(maximumHeight=10, textVisible=False)
        self.progress.setRange(0, 1)
        self.lbl_status = QLabel("Відкрийте фото")
        self.lbl_status.setWordWrap(True)
        v.addWidget(self.btn_gen)
        v.addLayout(f)
        v.addWidget(self.btn_save)
        v.addWidget(self.progress)
        v.addWidget(self.lbl_status)
        lv.addWidget(g)
        lv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(430)
        split.addWidget(scroll)

        # праворуч: вкладки
        self.tabs = QTabWidget()
        self.canvas = ZoneCanvas()
        self.canvas.zoneDrawn.connect(self._zone_drawn)
        self.canvas.zoneClicked.connect(self._canvas_clicked)
        self.canvas.zoneEdited.connect(self._zone_geometry_changed)
        self.canvas.deleteRequested.connect(lambda i: self.delete_zone())
        self.view_numbers = ImageView()
        self.view_color = ImageView()
        self.view_compare = ImageView()
        self.view_variants = ImageView()
        self.tabs.addTab(self.canvas, "Фото і зони")
        self.tabs.addTab(self.view_numbers, "Контури з номерами")
        self.tabs.addTab(self.view_color, "Кольори")
        self.tabs.addTab(self.view_compare, "Порівняння")
        self.tabs.addTab(self.view_variants, "Варіанти")
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.tabs, 4)
        self.tbl = QTableWidget(0, 8)
        self.tbl.setHorizontalHeaderLabels(["№", "Колір", "Код", "Назва", "Площа, мм²", "Ділянок", "Ємностей", "мл"])
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.verticalHeader().setVisible(False)
        self.lst_warn = QListWidget()
        self.tbl_var = QTableWidget(0, 9)
        self.tbl_var.setHorizontalHeaderLabels(["Режим", "Кольорів", "Оцінка", "ΔE", "SSIM", "Ділянок",
                                                "Без номера", "Виносок", "Статус"])
        self.tbl_var.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_var.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_var.verticalHeader().setVisible(False)
        self.tbl_var.setToolTip("Подвійний клік: застосувати варіант і створити превʼю")
        self.tbl_var.cellDoubleClicked.connect(self._apply_variant)
        self.variant_rows: list[dict] = []
        bottom = QTabWidget()
        bottom.addTab(self.tbl, "Специфікація фарб")
        bottom.addTab(self.lst_warn, "Попередження")
        bottom.addTab(self.tbl_var, "Варіанти")
        self.bottom = bottom
        rv.addWidget(bottom, 2)
        split.addWidget(right)
        split.setStretchFactor(1, 1)

        for w in (self.sp_w, self.sp_h, self.sp_colors, self.sp_cov, self.sp_k):
            w.valueChanged.connect(self._invalidate)
        for w in (self.cb_auto_h, self.cb_auto_colors, self.cb_cov_ok):
            w.toggled.connect(self._invalidate)
        self.cmb_mode.currentIndexChanged.connect(self._invalidate)

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("Файл")
        for text, fn, key in (("Відкрити фото…", self.open_photo, QKeySequence.StandardKey.Open),
                              ("Відкрити проєкт (папку замовлення)…", self.open_project_dialog, QKeySequence("Ctrl+Shift+O")),
                              ("Зони із файлу…", self.load_zones, None), ("Зони у файл…", self.save_zones, None),
                              ("Створити превʼю", self.generate, QKeySequence("Ctrl+R")),
                              ("Зберегти пакет…", self.save_package, QKeySequence.StandardKey.Save),
                              ("Скинути збережені налаштування", self.reset_prefs, None),
                              ("Вийти", self.close, QKeySequence.StandardKey.Quit)):
            a = QAction(text, self)
            a.triggered.connect(lambda _=False, f=fn: f())
            if key:
                a.setShortcut(key)
            m.addAction(a)
        em = self.menuBar().addMenu("Правка")
        self.act_undo = QAction("Відмінити", self)
        self.act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.act_undo.triggered.connect(lambda _=False: self.undo_zones())
        self.act_redo = QAction("Повторити", self)
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_redo.triggered.connect(lambda _=False: self.redo_zones())
        em.addAction(self.act_undo)
        em.addAction(self.act_redo)

    # ------------------------------------------------------------------ відмінити / повторити (зони)
    def _record(self, label: str, key=None) -> None:
        if not self._restoring:
            self.history.push((copy.deepcopy(self.zones), self.lst_zones.currentRow()), label, key)
        self._update_undo_actions()

    def _update_undo_actions(self) -> None:
        h = self.history
        for w, can, lab, pre in ((self.act_undo, h.can_undo, h.undo_label, "Відмінити"),
                                 (self.btn_undo, h.can_undo, h.undo_label, "↶ Відмінити"),
                                 (self.act_redo, h.can_redo, h.redo_label, "Повторити"),
                                 (self.btn_redo, h.can_redo, h.redo_label, "↷ Повторити")):
            w.setEnabled(can)
            w.setToolTip(f"{pre}: {lab}" if can else "")
            if w in (self.act_undo, self.act_redo):
                w.setText(f"{pre}: {lab}" if can else pre)

    def _restore(self, state, verb: str, label: str) -> None:
        zones, sel = state
        self._restoring = True
        try:
            self.zones = copy.deepcopy(zones)
            self._refresh_zone_list(sel if 0 <= sel < len(self.zones) else -1)
            self._invalidate()
        finally:
            self._restoring = False
        self._update_undo_actions()
        self.lbl_status.setText(f"{verb}: {label}.")

    def undo_zones(self) -> None:
        label = self.history.undo_label
        state = self.history.undo()
        if state is not None:
            self._restore(state, "Відмінено", label)

    def redo_zones(self) -> None:
        label = self.history.redo_label
        state = self.history.redo()
        if state is not None:
            self._restore(state, "Повторено", label)

    # ------------------------------------------------------------------ фото та зони
    def open_photo(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Фото", self.prefs.get("last_photo_dir"), "Зображення (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)")
        if not path:
            return
        self.photo = path
        self.original_name = None
        self.prefs.set("last_photo_dir", str(Path(path).parent))
        self.lbl_photo.setText(Path(path).name)
        self.res = None
        self._reload_canvas(fit=True)
        self.tabs.setCurrentIndex(0)

    def _schedule_reload(self, *_):
        self._reload_timer.start()

    def _reload_canvas(self, fit: bool = False) -> None:
        if not self.photo:
            return
        try:
            img = load_image(self.photo, self.sp_w.value(), None if self.cb_auto_h.isChecked() else self.sp_h.value(), 3.0)
        except Exception as e:
            QMessageBox.warning(self, "Не вдалося відкрити фото", str(e))
            self.photo = None
            self.lbl_photo.setText("файл не вибрано")
            self._update_buttons()
            return
        self.canvas.set_image(img.bgr, keep_view=not fit)
        self.canvas.set_zones(self.zones, self.lst_zones.currentRow())
        self.lbl_status.setText(f"Полотно {img.width_mm:.0f}×{img.height_mm:.0f} мм. "
                                "Позначте важливі місця (обличчя, очі) інструментами ▭ ◯ ⬠ і натисніть «Створити превʼю».")
        self._update_buttons()

    def _refresh_zone_list(self, select: int = -1) -> None:
        self.lst_zones.blockSignals(True)
        self.lst_zones.clear()
        for z in self.zones:
            self.lst_zones.addItem(QListWidgetItem(f'{z["name"]}  ·  {z["shape"]}  ·  вага {z["weight"]:g}'))
        if 0 <= select < len(self.zones):
            self.lst_zones.setCurrentRow(select)
        self.lst_zones.blockSignals(False)
        self.canvas.set_zones(self.zones, select)
        self._fill_zone_editor(select)

    def _fill_zone_editor(self, i: int) -> None:
        ok = 0 <= i < len(self.zones)
        self.ed_zname.setEnabled(ok)
        self.sp_zw.setEnabled(ok)
        self.btn_zdel.setEnabled(ok)
        self.ed_zname.blockSignals(True)
        self.sp_zw.blockSignals(True)
        self.ed_zname.setText(self.zones[i]["name"] if ok else "")
        self.sp_zw.setValue(self.zones[i]["weight"] if ok else 2.0)
        self.ed_zname.blockSignals(False)
        self.sp_zw.blockSignals(False)

    def _zone_drawn(self, z: dict) -> None:
        z["name"] = f"Зона {len(self.zones) + 1}"
        self.zones.append(z)
        self._refresh_zone_list(len(self.zones) - 1)
        self._invalidate()
        self._record("додано зону")

    def _zone_selected(self, i: int) -> None:
        self.canvas.set_zones(self.zones, i)
        self._fill_zone_editor(i)

    def _canvas_clicked(self, i: int) -> None:
        self._refresh_zone_list(i)

    def _zone_geometry_changed(self, i: int) -> None:
        """Зону пересунули або змінили розмір на фото (канва вже оновила self.zones[i])."""
        self._refresh_zone_list(i)
        self._invalidate()
        self._record("зміна положення або розміру зони")

    def _zone_edited(self, *_):
        i = self.lst_zones.currentRow()
        if not 0 <= i < len(self.zones):
            return
        self.zones[i]["name"] = self.ed_zname.text().strip() or f"Зона {i + 1}"
        self.zones[i]["weight"] = float(self.sp_zw.value())
        self._refresh_zone_list(i)
        self._invalidate()
        self._record("зміна назви або ваги зони", key=("edit", i))

    def delete_zone(self) -> None:
        i = self.lst_zones.currentRow()
        if 0 <= i < len(self.zones):
            del self.zones[i]
            self._refresh_zone_list(min(i, len(self.zones) - 1))
            self._invalidate()
            self._record("видалено зону")

    def load_zones(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Зони пріоритету", self.prefs.get("last_zones_dir"), "JSON (*.json)")
        if not path:
            return
        try:
            raw = load_zones_file(path)
            parse_zones(raw)
        except (ZoneError, OSError) as e:
            QMessageBox.warning(self, "Помилка в зонах", str(e))
            return
        self.prefs.set("last_zones_dir", str(Path(path).parent))
        self.zones = copy.deepcopy(raw)
        for i, z in enumerate(self.zones):
            z.setdefault("name", f"Зона {i + 1}")
            z["weight"] = float(z.get("weight", 2.0))
        if any(z.get("frame", "canvas") == "photo" for z in self.zones):
            QMessageBox.information(self, "Зони", "Зони з frame=photo буде застосовано, але на екрані їх контури "
                                    "показуються відносно обрізаного полотна.")
        self._refresh_zone_list(0 if self.zones else -1)
        self._invalidate()
        self._record("завантажено зони з файлу")

    def save_zones(self) -> None:
        if not self.zones:
            QMessageBox.information(self, "Зони", "Зон ще немає.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Зберегти зони", str(Path(self.prefs.get("last_zones_dir")) / "zones.json"),
                                              "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps({"zones": self.zones}, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ каталог
    def load_catalog_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Каталог фарб", self.prefs.get("last_catalog_dir"), "JSON (*.json)")
        if not path:
            return
        try:
            self.catalog = load_catalog(path)
        except (CatalogError, OSError) as e:
            QMessageBox.warning(self, "Помилка в каталозі", str(e))
            return
        self.lbl_cat.setText(f"{Path(path).name}: {len(self.catalog)} фарб")
        self.prefs.set("catalog_path", path)
        self.prefs.set("last_catalog_dir", str(Path(path).parent))
        self._invalidate()

    def clear_catalog(self) -> None:
        self.catalog = []
        self.prefs.set("catalog_path", "")
        self.lbl_cat.setText("каталог не задано (коди P-001…)")
        self._invalidate()

    # ------------------------------------------------------------------ генерація та збереження
    def make_settings(self) -> Settings:
        parse_zones(self.zones)               # ZoneError --- зрозуміле повідомлення
        return Settings(
            mode=self.cmb_mode.currentData(),
            n_colors=None if self.cb_auto_colors.isChecked() else self.sp_colors.value(),
            width_mm=self.sp_w.value(),
            height_mm=None if self.cb_auto_h.isChecked() else self.sp_h.value(),
            order_number=self.ed_order.text().strip() or "000001", project_name=self.ed_name.text().strip(),
            coverage_mm2_per_container=self.sp_cov.value() or None, safety_factor=self.sp_k.value(),
            coverage_confirmed=self.cb_cov_ok.isChecked(), zones=copy.deepcopy(self.zones), catalog=list(self.catalog))

    def _busy(self, on: bool, text: str = "") -> None:
        self.progress.setRange(0, 0 if on else 1)
        if text:
            self.lbl_status.setText(text)
        self._update_buttons(busy=on)

    def _update_buttons(self, busy: bool = False) -> None:
        has = bool(self.photo)
        self.btn_gen.setEnabled(has and not busy)
        self.btn_cmp.setEnabled(has and not busy)
        self.btn_save.setEnabled(self.res is not None and not busy)
        self.btn_open.setEnabled(not busy)
        self.btn_open_proj.setEnabled(not busy)

    def _invalidate(self, *_):
        if self.res is not None:
            self.res = None
            self.lbl_status.setText("Налаштування змінено: створіть превʼю знову, щоб зберегти пакет.")
            self._update_buttons()

    def generate(self) -> None:
        if not self.photo or self.job:
            return
        try:
            s = self.make_settings()
        except ZoneError as e:
            QMessageBox.warning(self, "Помилка в зонах", str(e))
            return
        photo = self.photo
        self.res = None
        self._busy(True, "Створення превʼю… (зазвичай 10–40 с)")
        self.job = Job(lambda: run_pipeline(photo, s), self)
        self.job.done.connect(self._generated)
        self.job.failed.connect(self._job_failed)
        self.job.finished.connect(self._job_finished)
        self.job.start()

    def _job_finished(self) -> None:
        self.job = None
        self._busy(False)
        if self._pending_apply is not None:          # відкладене застосування обраного варіанта
            row, self._pending_apply = self._pending_apply, None
            self._apply_variant(row)

    def _job_failed(self, msg: str) -> None:
        self.lbl_status.setText("Помилка")
        QMessageBox.critical(self, "Помилка", msg)

    def _generated(self, res) -> None:
        self.res = res
        self.view_numbers.set_image(res.numbered_img)
        self.view_color.set_image(res.color_img)
        self.view_compare.set_image(res.compare_img)
        self.tabs.setCurrentWidget(self.view_numbers)
        self._fill_spec(res)
        self._fill_warnings(res)
        r = res.report
        t = res.spec["totals"]
        self.lbl_status.setText(
            f"Готово: {r['regions_final']} ділянок, {t['paints']} кольорів, {t['containers']} ємностей "
            f"({t['total_ml']:g} мл){' (орієнтовно)' if res.spec['calculation']['provisional'] else ''}. "
            f"Номерів на виносках: {r.get('regions_with_leader', 0)}, без номера: {r['regions_without_number_room']}.")
        self._update_buttons()

    def _fill_spec(self, res) -> None:
        paints = res.spec["paints"]
        self.tbl.setRowCount(len(paints))
        for i, p in enumerate(paints):
            vals = [p["number"], "", p["paint_code"], p["paint_name"], f'{p["area_mm2"]:,.0f}'.replace(",", " "),
                    p["regions"], p["containers"], f'{p["total_ml"]:g}']
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if j == 1:
                    it.setBackground(QBrush(QColor(p["hex"])))
                self.tbl.setItem(i, j, it)
        self.tbl.resizeColumnsToContents()

    def _fill_warnings(self, res) -> None:
        self.lst_warn.clear()
        order = {"critical": 0, "warning": 1, "info": 2}
        for w in sorted(res.warnings, key=lambda w: order.get(w["severity"], 3)):
            it = QListWidgetItem(f'[{w["severity"]}] {w["code"]}: {w["message"]}')
            it.setForeground(QBrush(QColor(SEV_COLOR.get(w["severity"], "#000"))))
            it.setToolTip(w.get("recommendation", ""))
            self.lst_warn.addItem(it)
        crit = sum(1 for w in res.warnings if w["severity"] == "critical")
        self.bottom.setTabText(1, f"Попередження ({len(res.warnings)}{', критичних ' + str(crit) if crit else ''})")

    def save_package(self, folder: str | None = None, force: bool = False) -> None:
        if self.res is None or self.job:
            return
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "Куди зберегти пакет замовлення", self.prefs.get("last_save_dir"))
        if not folder:
            return
        self.prefs.set("last_save_dir", folder)
        res, photo = self.res, self.photo
        res.settings.order_number = self.ed_order.text().strip() or "000001"
        res.settings.project_name = self.ed_name.text().strip()
        self._busy(True, "Збереження пакета…")
        oname = self.original_name
        self.job = Job(lambda: build_package(res, folder, photo, force=force, original_name=oname), self)
        self.job.done.connect(lambda info: self._saved(info, folder))
        self.job.failed.connect(self._job_failed)
        self.job.finished.connect(self._job_finished)
        self.job.start()

    def _saved(self, info: dict, folder: str) -> None:
        if info.get("blocked"):
            self.lbl_status.setText("Виробничі файли заблоковано критичними помилками.")
            ans = QMessageBox.question(
                self, "Пакет заблоковано",
                "Є критичні попередження: файли для друку й виробництва не створено.\n"
                "Створити їх попри помилки (лише після ручної перевірки)?")
            if ans == QMessageBox.StandardButton.Yes:
                QTimer.singleShot(0, lambda: self.save_package(folder, force=True))
            return
        self.lbl_status.setText(f"Пакет збережено: {info['dir']}")
        QMessageBox.information(self, "Готово", f"Пакет збережено:\n{info['dir']}\n\n"
                                "Пізніше його можна відкрити без перерахунку: «Відкрити проєкт».")

    # ------------------------------------------------------------------ порівняння варіантів
    def compare_variants(self) -> None:
        if not self.photo or self.job:
            return
        try:
            s = self.make_settings()
        except ZoneError as e:
            QMessageBox.warning(self, "Помилка в зонах", str(e))
            return
        photo = self.photo
        variants = default_variants(s)
        self.res = None
        self._busy(True, f"Порівняння {len(variants)} варіантів… (кілька хвилин; можна не чекати біля екрана)")
        self.job = Job(lambda: select_best(photo, s, variants), self)
        self.job.done.connect(self._compared)
        self.job.failed.connect(self._job_failed)
        self.job.finished.connect(self._job_finished)
        self.job.start()

    def _compared(self, out) -> None:
        chosen, rows, best, report, sheet = out
        self.variant_rows = rows
        self.view_variants.set_image(sheet)
        self.tbl_var.setRowCount(len(rows))
        for i, r in enumerate(rows):
            if "error" in r:
                vals = [MODE_NAMES[r["mode"]], r["colors_requested"], "", "", "", "", "", "", "помилка"]
            else:
                status = "ОБРАНО" if i == best else ("заблоковано" if r["critical"] else "")
                vals = [MODE_NAMES[r["mode"]], r["colors_requested"], f'{r["score"]:.3f}',
                        f'{r["delta_e76_weighted"]:.1f}', f'{r["ssim"]:.2f}', r["regions"],
                        r["regions_no_number"], r["regions_leader"], status]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if i == best:
                    it.setBackground(QBrush(QColor("#d9f2d9")))
                self.tbl_var.setItem(i, j, it)
        self.tbl_var.resizeColumnsToContents()
        self.bottom.setCurrentWidget(self.tbl_var)
        if chosen is None:
            self.tabs.setCurrentWidget(self.view_variants)
            self.lbl_status.setText("Усі варіанти мають критичні помилки або не збудувалися; перегляньте таблицю.")
            return
        note = f" {report['note']}" if report.get("note") else ""
        self.lbl_status.setText(f"Обрано: {MODE_NAMES[chosen.mode]}, {chosen.n_colors} кольорів.{note}")
        self._pending_apply = best           # задача ще не завершена: застосуємо в _job_finished

    def _apply_variant(self, row: int, _col: int = 0) -> None:
        if not 0 <= row < len(self.variant_rows) or "error" in self.variant_rows[row] or self.job:
            return
        r = self.variant_rows[row]
        for w in (self.cmb_mode, self.cb_auto_colors, self.sp_colors):
            w.blockSignals(True)
        self.cmb_mode.setCurrentIndex(list(PRESETS).index(r["mode"]))
        self.cb_auto_colors.setChecked(False)
        self.sp_colors.setEnabled(True)
        self.sp_colors.setValue(r["colors_requested"])
        for w in (self.cmb_mode, self.cb_auto_colors, self.sp_colors):
            w.blockSignals(False)
        QTimer.singleShot(0, self.generate)

    # ------------------------------------------------------------------ збережені налаштування
    def _load_prefs(self) -> None:
        p = self.prefs
        widgets = (self.sp_w, self.sp_h, self.cmb_mode, self.cb_auto_h, self.cb_auto_colors, self.sp_colors,
                   self.sp_cov, self.sp_k, self.cb_cov_ok)
        for w in widgets:
            w.blockSignals(True)
        self.sp_w.setValue(p.get("width_mm"))
        self.cb_auto_h.setChecked(p.get("auto_height"))
        self.sp_h.setValue(p.get("height_mm"))
        self.sp_h.setEnabled(not self.cb_auto_h.isChecked())
        self.cmb_mode.setCurrentIndex(list(PRESETS).index(p.get("mode")))
        self.cb_auto_colors.setChecked(p.get("auto_colors"))
        self.sp_colors.setValue(p.get("colors"))
        self.sp_colors.setEnabled(not self.cb_auto_colors.isChecked())
        self.sp_cov.setValue(p.get("coverage_mm2"))
        self.sp_k.setValue(p.get("safety_factor"))
        self.cb_cov_ok.setChecked(p.get("coverage_confirmed"))
        for w in widgets:
            w.blockSignals(False)
        cat = p.get("catalog_path")
        if cat:
            try:
                self.catalog = load_catalog(cat)
                self.lbl_cat.setText(f"{Path(cat).name}: {len(self.catalog)} фарб")
            except (CatalogError, OSError):
                self.lbl_cat.setText("збережений каталог недоступний (каталог не задано)")
        g = p.geometry()
        if not g.isEmpty():
            self.restoreGeometry(g)

    def _save_prefs(self) -> None:
        p = self.prefs
        p.set("width_mm", float(self.sp_w.value()))
        p.set("auto_height", self.cb_auto_h.isChecked())
        p.set("height_mm", float(self.sp_h.value()))
        p.set("mode", self.cmb_mode.currentData())
        p.set("auto_colors", self.cb_auto_colors.isChecked())
        p.set("colors", int(self.sp_colors.value()))
        p.set("coverage_mm2", float(self.sp_cov.value()))
        p.set("safety_factor", float(self.sp_k.value()))
        p.set("coverage_confirmed", self.cb_cov_ok.isChecked())
        p.set_geometry(self.saveGeometry())
        p.sync()

    def reset_prefs(self) -> None:
        self.prefs.reset()
        self._load_prefs()
        QMessageBox.information(self, "Налаштування", "Збережені налаштування скинуто до типових.")

    def closeEvent(self, e):
        self._save_prefs()
        super().closeEvent(e)

    # ------------------------------------------------------------------ відкриття проєкту
    def open_project_dialog(self, folder: str | None = None) -> None:
        if self.job:
            return
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "Папка замовлення (order_XXXXXX)", self.prefs.get("last_save_dir"))
        if not folder:
            return
        self.res = None
        self._busy(True, "Відкриття проєкту…")
        self.job = Job(lambda: open_project(folder), self)
        self.job.done.connect(self._project_opened)
        self.job.failed.connect(self._job_failed)
        self.job.finished.connect(self._job_finished)
        self.job.start()

    def _project_opened(self, res) -> None:
        s = res.settings
        widgets = (self.sp_w, self.sp_h, self.cmb_mode, self.cb_auto_h, self.cb_auto_colors, self.sp_colors,
                   self.sp_cov, self.sp_k, self.cb_cov_ok, self.ed_order, self.ed_name)
        for w in widgets:
            w.blockSignals(True)
        self.sp_w.setValue(s.width_mm)
        self.cb_auto_h.setChecked(s.height_mm is None)
        self.sp_h.setValue(s.height_mm if s.height_mm is not None else res.height_mm)
        self.sp_h.setEnabled(s.height_mm is not None)
        self.cmb_mode.setCurrentIndex(list(PRESETS).index(s.mode))
        self.cb_auto_colors.setChecked(s.n_colors is None)
        self.sp_colors.setValue(s.n_colors if s.n_colors is not None else self.sp_colors.value())
        self.sp_colors.setEnabled(s.n_colors is not None)
        self.sp_cov.setValue(s.coverage_mm2_per_container or 0)
        self.sp_k.setValue(s.safety_factor)
        self.cb_cov_ok.setChecked(bool(s.coverage_confirmed))
        self.ed_order.setText(s.order_number)
        self.ed_name.setText(s.project_name)
        for w in widgets:
            w.blockSignals(False)
        self.catalog = list(s.catalog)
        self.lbl_cat.setText(f"каталог із проєкту: {len(self.catalog)} фарб" if self.catalog
                             else "каталог не задано (коди P-001…)")
        self.zones = copy.deepcopy(list(s.zones))
        for i, z in enumerate(self.zones):
            z.setdefault("name", f"Зона {i + 1}")
            z["weight"] = float(z.get("weight", 2.0))
        self.photo = str(res.source_photo)
        self.original_name = res.original_name
        self.lbl_photo.setText(f"{res.original_name} (з проєкту)")
        self._reload_timer.stop()
        self._reload_canvas(fit=True)
        self._refresh_zone_list(0 if self.zones else -1)
        self.history.reset((copy.deepcopy(self.zones), self.lst_zones.currentRow()))   # історія нового проєкту
        self._update_undo_actions()
        self.res = res                      # _reload_canvas/_refresh_zone_list не скасовують результат: він встановлюється останнім
        self._generated(res)
        self.lbl_status.setText("Проєкт відкрито без перерахунку. " + self.lbl_status.text())
        self.prefs.set("last_save_dir", str(Path(res.source_photo).parent.parent.parent))
