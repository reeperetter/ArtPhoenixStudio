# Сторонні компоненти / Third-party components

ArtPhoenix Studio використовує відкриті бібліотеки. Ліцензії наведено за метаданими пакетів, версії — станом на збирання.
Перед комерційним розповсюдженням перевірте актуальні тексти ліцензій за посиланнями.

| Компонент | Призначення | Ліцензія | Джерело |
|---|---|---|---|
| NumPy | масиви, обчислення | BSD-3-Clause | https://numpy.org |
| SciPy | наукові обчислення | BSD-3-Clause | https://scipy.org |
| scikit-image | обробка зображень | BSD-3-Clause | https://scikit-image.org |
| scikit-learn | кластеризація | BSD-3-Clause | https://scikit-learn.org |
| OpenCV (opencv-python-headless) | обробка зображень | Apache-2.0 (колеса містять також FFmpeg під LGPL-2.1) | https://opencv.org |
| Pillow | читання й запис зображень | MIT-CMU (HPND) | https://python-pillow.org |
| Shapely | геометрія контурів | BSD-3-Clause | https://shapely.readthedocs.io |
| ReportLab | створення PDF | BSD | https://www.reportlab.com/opensource/ |
| openpyxl | запис Excel (.xlsx) | MIT | https://openpyxl.readthedocs.io |
| Qt for Python (PySide6) | графічний інтерфейс | LGPL-3.0 / GPL-3.0 / комерційна | https://doc.qt.io/qtforpython-6/ |
| PyInstaller (лише збирання) | пакування в .exe | GPL-2.0 з винятком для завантажувача | https://pyinstaller.org |

## Примітки

- **Qt / PySide6** поширюється за LGPL-3.0: у збірці Windows бібліотеки Qt лежать окремими DLL, їх можна замінити; текст ліцензії треба додавати до дистрибутива. Юридичні умови розповсюдження (особливо продаж програми) перевірте самостійно: https://www.qt.io/licensing/
- **PyInstaller** не накладає GPL на зібрану програму (виняток для завантажувача): https://pyinstaller.org/en/stable/license.html
- Палітри в `assets/palettes` складено програмою з екранних кольорів і не є продуктом жодного виробника фарб.
- Штучний інтелект і мережеві сервіси не використовуються.
