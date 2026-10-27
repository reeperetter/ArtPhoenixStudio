"""Діалог параметрів експорту для друку (PrintProfile)."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
                               QSpinBox, QVBoxLayout)

from ..export.print_ready import PrintProfile

TILE_CHOICES = (("без розбиття", ""), ("аркуші A4", "A4"), ("аркуші A3", "A3"), ("аркуші A2", "A2"))
FORMAT_CHOICES = (("TIFF (LZW)", "tiff"), ("PNG", "png"), ("без растру", "none"))


class PrintProfileDialog(QDialog):
    def __init__(self, profile: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Параметри друку")
        p = PrintProfile.from_dict(profile) if profile else PrintProfile()
        v = QVBoxLayout(self)
        self.cb_on = QCheckBox("Створювати файли для друку (папка print/print_ready/ у пакеті)")
        self.cb_on.setChecked(profile is not None)
        v.addWidget(self.cb_on)
        f = QFormLayout()
        self.sp_bleed = QDoubleSpinBox(minimum=0, maximum=20, decimals=1, singleStep=0.5, suffix=" мм", value=p.bleed_mm)
        self.sp_wrap = QDoubleSpinBox(minimum=0, maximum=100, decimals=1, singleStep=1, suffix=" мм", value=p.wrap_mm)
        self.cb_marks = QCheckBox("мітки різу, позначки країв полотна, службовий рядок")
        self.cb_marks.setChecked(p.marks)
        self.sp_dpi = QSpinBox(minimum=72, maximum=1200, singleStep=50, value=p.dpi)
        self.cmb_fmt = QComboBox()
        for t, k in FORMAT_CHOICES:
            self.cmb_fmt.addItem(t, k)
        self.cmb_fmt.setCurrentIndex(max(0, self.cmb_fmt.findData(p.raster_format)))
        self.cmb_tiles = QComboBox()
        for t, k in TILE_CHOICES:
            self.cmb_tiles.addItem(t, k)
        self.cmb_tiles.setCurrentIndex(max(0, self.cmb_tiles.findData(p.tiles.upper())))
        self.sp_ov = QDoubleSpinBox(minimum=0, maximum=50, decimals=1, singleStep=1, suffix=" мм", value=p.tile_overlap_mm)
        self.sp_mg = QDoubleSpinBox(minimum=0, maximum=30, decimals=1, singleStep=1, suffix=" мм", value=p.sheet_margin_mm)
        f.addRow("Припуск (bleed)", self.sp_bleed)
        f.addRow("Поле під загин на підрамник", self.sp_wrap)
        f.addRow("Мітки", self.cb_marks)
        f.addRow("Роздільна здатність", self.sp_dpi)
        f.addRow("Формат растру", self.cmb_fmt)
        f.addRow("Розбиття на аркуші", self.cmb_tiles)
        f.addRow("Перекриття аркушів", self.sp_ov)
        f.addRow("Непридатне поле принтера", self.sp_mg)
        v.addLayout(f)
        v.addWidget(QLabel("Припуск і поле загортання лишаються білими: контур доходить лише до краю полотна."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def profile(self) -> dict | None:
        """None, якщо експорт для друку вимкнено."""
        if not self.cb_on.isChecked():
            return None
        return PrintProfile(bleed_mm=self.sp_bleed.value(), wrap_mm=self.sp_wrap.value(), marks=self.cb_marks.isChecked(),
                            dpi=self.sp_dpi.value(), raster_format=self.cmb_fmt.currentData(),
                            tiles=self.cmb_tiles.currentData(), tile_overlap_mm=self.sp_ov.value(),
                            sheet_margin_mm=self.sp_mg.value()).to_dict()
