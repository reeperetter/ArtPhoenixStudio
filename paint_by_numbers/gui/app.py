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
    if len(app.arguments()) > 1:
        w.open_photo(app.arguments()[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
