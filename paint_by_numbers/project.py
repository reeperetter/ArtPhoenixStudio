"""Відкриття збереженого проєкту (розділ 16.2 ТЗ): повернення до замовлення без повного перерахунку.

Пакет замовлення `order_XXXXXX/` уже є проєктом: `project/project.json` зберігає налаштування (зони, каталог,
норму покриття тощо), `project/regions.npz` --- готове розбиття на ділянки й палітру, `source/` --- оригінал фото.
Відкриття пропускає найдорожчі кроки (квантування кольорів, злиття ділянок) і відновлює лише геометрію, номери,
специфікацію й превʼю: на тестовому портреті це 2,3 с замість 5,9 с (виграш більший для щільніших фото), а результат збігається з первинним (перевіряє тест)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .generate import Result, run_pipeline
from .image_io.loader import load_image
from .settings import ALGORITHM_VERSION, PROJECT_FORMAT_VERSION, Settings


class ProjectError(ValueError):
    """Проєкт не вдалося відкрити (повідомлення зрозуміле оператору)."""


def _find_dir(path: str | Path) -> Path:
    p = Path(path)
    if p.is_file() and p.name == "project.json":
        p = p.parent.parent
    if not (p / "project" / "project.json").is_file():
        raise ProjectError(f"«{p}» не схоже на папку проєкту: немає project/project.json.")
    return p


def open_project(path: str | Path) -> Result:
    d = _find_dir(path)
    try:
        meta = json.loads((d / "project" / "project.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ProjectError(f"Файл project.json пошкоджено: {e}")
    ver = meta.get("project_format_version")
    if ver != PROJECT_FORMAT_VERSION:
        raise ProjectError(f"Непідтримувана версія формату проєкту: {ver} (потрібна {PROJECT_FORMAT_VERSION}).")
    try:
        settings = Settings.from_dict(meta["settings"])
        src = d / meta["source"]["file"]
        original_name = meta["source"].get("original_name", src.name)
        eff = meta.get("effective", {})
        npz_path = d / meta.get("regions_file", "project/regions.npz")
    except (KeyError, TypeError) as e:
        raise ProjectError(f"У project.json бракує поля {e}.")
    if not src.is_file():
        raise ProjectError(f"Немає оригіналу фото: {src}.")
    try:
        with np.load(npz_path) as z:
            data = {k: z[k] for k in z.files}
    except (OSError, ValueError) as e:
        raise ProjectError(f"Не вдалося прочитати {npz_path.name}: {e}")
    for key in ("labels", "region_color", "palette_lab"):
        if key not in data:
            raise ProjectError(f"У {npz_path.name} бракує масиву «{key}».")
    if "palette_lab_raw" in data:                    # палітра до підбору фарб каталогу (підбір повторюється)
        data["palette_lab"] = data["palette_lab_raw"]
    data.setdefault("n_before", np.int64(len(data["region_color"])))
    data["merged_for_numbers"] = eff.get("merged_for_numbers", 0)

    # перевірка узгодженості розбиття з фото й налаштуваннями
    img = load_image(str(src), settings.width_mm, settings.height_mm, settings.ppm)
    h, w = img.bgr.shape[:2]
    lab = data["labels"]
    if lab.shape != (h, w):
        raise ProjectError(f"Розбиття ({lab.shape[1]}x{lab.shape[0]}) не збігається з фото ({w}x{h}): "
                           "налаштування полотна змінилися або файли пошкоджено.")
    rc = data["region_color"]
    if lab.min() < 0 or lab.max() >= len(rc) or rc.min() < 0 or rc.max() >= len(data["palette_lab"]):
        raise ProjectError("Розбиття містить неприпустимі номери ділянок або кольорів.")

    res = run_pipeline(src, settings, restored=data)
    res.report["photo"] = original_name
    res.report["restored_from_project"] = True
    if meta.get("algorithm_version") != ALGORITHM_VERSION:
        res.warnings.append({
            "code": "PROJECT_VERSION_DIFFERS", "severity": "info",
            "message": f"Проєкт створено версією алгоритму {meta.get('algorithm_version')}, зараз {ALGORITHM_VERSION}: "
                       "контури й номери перераховано поточною версією.",
            "recommendation": "Перегляньте результат перед збереженням пакета."})
    res.source_photo = src
    res.original_name = original_name
    return res
