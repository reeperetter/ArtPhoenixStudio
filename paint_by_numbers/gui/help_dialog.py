"""Вбудована інструкція користувача: розділи зліва, пошук, текст справа (Markdown з assets/help/manual_uk.md)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QSplitter, QTextBrowser,
                               QVBoxLayout)

from ..export.pdf import resource_dir


def manual_path() -> Path:
    return resource_dir() / "assets" / "help" / "manual_uk.md"


def load_sections(path: Path | None = None) -> list[tuple[str, str]]:
    """[(заголовок, текст Markdown з заголовком)] за рядками, що починаються з «## »."""
    text = (path or manual_path()).read_text(encoding="utf-8")
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), [line]))
        elif sections:
            sections[-1][1].append(line)
    return [(t, "\n".join(body).strip() + "\n") for t, body in sections]


class HelpDialog(QDialog):
    def __init__(self, parent=None, section: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Інструкція")
        self.resize(980, 680)
        self.sections = load_sections()
        v = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Пошук в інструкції…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        v.addWidget(self.search)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.lst = QListWidget()
        self.lst.setMaximumWidth(280)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        split.addWidget(self.lst)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        h = QHBoxLayout()
        h.addWidget(split)
        v.addLayout(h)
        self.lst.currentRowChanged.connect(self._show)
        self._fill(self.sections)
        self.show_section(section)

    def _fill(self, items: list[tuple[str, str]]) -> None:
        self.lst.blockSignals(True)
        self.lst.clear()
        for title, _ in items:
            self.lst.addItem(QListWidgetItem(title))
        self.lst.blockSignals(False)
        self._visible = items

    def _filter(self, q: str) -> None:
        q = q.strip().casefold()
        items = [s for s in self.sections if not q or q in s[0].casefold() or q in s[1].casefold()]
        self._fill(items)
        if items:
            self.lst.setCurrentRow(0)
            if q:
                self.view.find(self.search.text().strip())
        else:
            self.view.setMarkdown("*Нічого не знайдено.*")

    def _show(self, row: int) -> None:
        if 0 <= row < len(self._visible):
            self.view.setMarkdown(self._visible[row][1])

    def show_section(self, title: str | None) -> None:
        """Відкриває розділ із заголовком, що містить `title` (без урахування регістру); без збігу --- перший."""
        if self.search.text():
            self.search.clear()
        row = 0
        if title:
            t = title.casefold()
            for i, (name, _) in enumerate(self._visible):
                if t in name.casefold():
                    row = i
                    break
        self.lst.setCurrentRow(row)
        self._show(row)
