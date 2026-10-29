# -*- mode: python ; coding: utf-8 -*-
# Збірка: pyinstaller packaging/pbn.spec --noconfirm --clean   (див. packaging/build_windows.bat)
# Результат: dist/ArtPhoenixStudio/ з двома програмами:
#   ArtPhoenixStudio.exe  --- графічний інтерфейс (без консолі)
#   ArtPhoenixStudio-cli.exe --- командний рядок і самоперевірка (--selftest)
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(root, "paint_by_numbers", "assets", "icons", "app.ico")     # значок .exe (Windows)

datas = [
    (os.path.join(root, "paint_by_numbers", "assets"), "paint_by_numbers/assets"),
    (os.path.join(root, "examples"), "examples"),
    (os.path.join(root, "README.md"), "."),
]
datas += collect_data_files("skimage")
hidden = (collect_submodules("paint_by_numbers") + collect_submodules("sklearn.utils")
          + collect_submodules("skimage.metrics") + ["sklearn.neighbors._partition_nodes"])
excludes = ["tkinter", "matplotlib", "IPython", "pytest", "cairosvg", "PyQt5", "PyQt6", "PySide2",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
            "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization"]


def analysis(script):
    return Analysis([os.path.join(root, script)], pathex=[root], datas=datas, hiddenimports=hidden,
                    excludes=excludes, noarchive=False)


a_gui, a_cli = analysis("main_gui.py"), analysis("main.py")
MERGE((a_gui, "main_gui", "ArtPhoenixStudio"), (a_cli, "main", "ArtPhoenixStudio-cli"))

pyz_gui, pyz_cli = PYZ(a_gui.pure), PYZ(a_cli.pure)
exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="ArtPhoenixStudio", console=False, icon=ICON)
exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="ArtPhoenixStudio-cli", console=True, icon=ICON)
coll = COLLECT(exe_gui, a_gui.binaries, a_gui.datas, exe_cli, a_cli.binaries, a_cli.datas,
               strip=False, upx=False, name="ArtPhoenixStudio")
