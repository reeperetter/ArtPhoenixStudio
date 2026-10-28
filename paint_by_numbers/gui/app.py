from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("Для інтерфейсу потрібен PySide6: pip install PySide6", file=sys.stderr)
        return 1
    from .main_window import MainWindow
    app = QApplication(argv if argv is not None else sys.argv)
    w = MainWindow()
    w.show()
    if not w.prefs.get("help_seen"):                  # перший запуск: запропонувати інструкцію
        from PySide6.QtWidgets import QMessageBox
        w.prefs.set("help_seen", True)
        w.prefs.sync()
        if QMessageBox.question(w, "Ласкаво просимо", "Відкрити коротку інструкцію? Її завжди можна відкрити клавішею F1."
                                ) == QMessageBox.StandardButton.Yes:
            w.show_help("Швидкий старт")
    if len(app.arguments()) > 1:
        w.open_photo(app.arguments()[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
