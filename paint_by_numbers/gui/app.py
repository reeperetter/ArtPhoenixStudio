from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is required for the interface / Для інтерфейсу потрібен PySide6: uv sync --extra gui", file=sys.stderr)
        return 1
    from .. import i18n
    from . import branding
    from .prefs import Prefs
    branding.set_windows_app_id()
    app = QApplication(argv if argv is not None else sys.argv)
    prefs = Prefs()
    lang = prefs.get("language")
    app.setApplicationName(branding.APP_NAME)
    app.setApplicationDisplayName(branding.APP_NAME)
    app.setWindowIcon(branding.app_icon())                  # іконка вікон, діалогів і панелі завдань
    if lang not in i18n.LANGUAGES:                          # перший запуск: мову треба обрати
        from .language_dialog import choose_language
        lang = choose_language()
        prefs.set("language", lang)
        prefs.sync()
    i18n.set_language(lang)                                 # до імпорту вікон: їхні константи перекладаються під час імпорту
    from .main_window import MainWindow
    w = MainWindow(prefs)
    w.show()
    if not w.prefs.get("help_seen"):                  # перший запуск: запропонувати інструкцію
        from PySide6.QtWidgets import QMessageBox
        w.prefs.set("help_seen", True)
        w.prefs.sync()
        if QMessageBox.question(w, i18n.tr(f"Ласкаво просимо до {branding.APP_NAME}"),
                                i18n.tr("Відкрити коротку інструкцію? Її завжди можна відкрити клавішею F1.")
                                ) == QMessageBox.StandardButton.Yes:
            w.show_help(i18n.tr("Швидкий старт"))
    if len(app.arguments()) > 1:
        w.open_photo(app.arguments()[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
