"""Пакетна обробка: багато фото підряд, кожне --- окреме замовлення `order_XXXXXX/` (розділ 16 ТЗ).

Вхід: папка з фото або CSV-маніфест (колонки: file; необовʼязково order, name, width_mm, height_mm, mode,
colors, zones). Поруч із фото автоматично підхоплюється файл зон `<імʼя>.zones.json`. Одне збійне фото не
зупиняє решту; результат --- `batch_report.csv/json` у кореневій папці. Фото обробляються паралельно в
окремих процесах, кожне пишеться у власну папку, тож конфліктів немає. Детерміновано: однакові вхідні
дані дають однакові пакети незалежно від кількості процесів."""
from __future__ import annotations

import concurrent.futures as cf
import csv
import dataclasses
import json
import multiprocessing as mp
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .compare import generate_best
from .generate import generate
from .palette.catalog import CatalogError
from .pipeline.priority_zones import ZoneError, load_zones_file, parse_zones
from .project import ProjectError
from .quality.warnings import summarize
from .settings import ALGORITHM_VERSION, PRESETS, Settings

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
SIZE_RANGE = (50.0, 3000.0)
REPORT_COLUMNS = ["file", "order", "status", "regions", "colors", "containers", "total_ml", "critical", "warnings",
                  "provisional", "seconds", "message"]


@dataclass
class BatchItem:
    photo: Path
    order: str
    name: str
    settings: Settings | None          # None, якщо рядок має помилку
    error: str = ""


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def safe_order(text: str) -> str:
    """Номер замовлення потрапляє в імʼя папки: лишаємо літери, цифри, «_» і «-»."""
    out = re.sub(r"[^\w\-]+", "_", text.strip(), flags=re.UNICODE).strip("_")
    return out or "order"


def discover(folder: str | Path) -> list[Path]:
    p = Path(folder)
    if not p.is_dir():
        raise ValueError(f"«{p}» не є папкою.")
    return sorted((f for f in p.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXT
                   and not f.name.startswith(".")), key=lambda f: natural_key(f.name))


def _num(text: str, name: str, lo: float, hi: float) -> float:
    try:
        v = float(str(text).strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"поле «{name}» має бути числом")
    if not lo <= v <= hi:
        raise ValueError(f"поле «{name}» = {v:g} поза межами {lo:g}..{hi:g}")
    return v


def read_manifest(path: str | Path) -> list[dict]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"Не вдалося прочитати маніфест: {e}")
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") >= first.count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    if not rows or "file" not in {(k or "").strip().lower() for k in rows[0]}:
        raise ValueError("У маніфесті має бути колонка «file» (і хоча б один рядок).")
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]


def build_items(source: str | Path, base: Settings, numbering: str = "name", start: int = 1,
                prefix: str = "") -> list[BatchItem]:
    """Складає завдання. Помилки окремих рядків не кидаються, а потрапляють у `BatchItem.error`."""
    src = Path(source)
    if src.is_dir():
        raw = [{"file": str(f)} for f in discover(src)]
        root = src
    else:
        raw = read_manifest(src)
        root = src.parent
    items: list[BatchItem] = []
    seen: dict[str, str] = {}
    for i, r in enumerate(raw):
        photo = Path(r["file"])
        photo = photo if photo.is_absolute() else root / photo
        order = safe_order(r["order"]) if r.get("order") else (
            safe_order(prefix + photo.stem) if numbering == "name" else f"{prefix}{start + i:06d}")
        name = r.get("name") or photo.stem
        err = ""
        s = None
        try:
            if not photo.is_file():
                raise ValueError("файл не знайдено")
            if photo.suffix.lower() not in IMAGE_EXT:
                raise ValueError("непідтримуваний тип файлу")
            kw: dict = {}
            if r.get("width_mm"):
                kw["width_mm"] = _num(r["width_mm"], "width_mm", *SIZE_RANGE)
            if r.get("height_mm"):
                kw["height_mm"] = _num(r["height_mm"], "height_mm", *SIZE_RANGE)
            if r.get("mode"):
                if r["mode"] not in PRESETS:
                    raise ValueError(f"невідомий режим «{r['mode']}» (є: {', '.join(PRESETS)})")
                kw["mode"] = r["mode"]
            if r.get("colors"):
                kw["n_colors"] = int(_num(r["colors"], "colors", 4, 36))
            zf = Path(r["zones"]) if r.get("zones") else photo.with_name(photo.stem + ".zones.json")
            zf = zf if zf.is_absolute() else (root / zf)
            zones = base.zones
            if r.get("zones") or zf.is_file():
                try:
                    zones = load_zones_file(zf)
                    parse_zones(zones)
                except (ZoneError, OSError) as e:
                    raise ValueError(f"зони: {e}")
            if order in seen:
                raise ValueError(f"номер замовлення «{order}» уже використано для «{seen[order]}»")
            s = dataclasses.replace(base, order_number=order, project_name=name, zones=zones, **kw)
            seen[order] = photo.name
        except ValueError as e:
            err, s = str(e), None
        items.append(BatchItem(photo, order, name, s, err))
    return items


def _already_done(out_root: Path, order: str) -> bool:
    q = out_root / f"order_{order}" / "quality" / "quality_report.json"
    try:
        return q.is_file() and not json.loads(q.read_text(encoding="utf-8")).get("blocked", True)
    except (OSError, json.JSONDecodeError):
        return False


def _row(item: BatchItem, status: str, message: str = "", res=None, seconds: float = 0.0) -> dict:
    row = {"file": item.photo.name, "order": item.order, "status": status, "regions": "", "colors": "",
           "containers": "", "total_ml": "", "critical": "", "warnings": "", "provisional": "",
           "seconds": round(seconds, 1), "message": message}
    if res is not None:
        sm, t = summarize(res.warnings), res.spec["totals"]
        row.update(regions=res.report["regions_final"], colors=t["paints"], containers=t["containers"],
                   total_ml=t["total_ml"], critical=sm["critical"], warnings=sm["warning"],
                   provisional=bool(res.spec["calculation"]["provisional"]))
    return row


def _work(args) -> dict:
    """Виконується в окремому процесі: повне створення пакета для одного фото."""
    item, out_root, compare, force = args
    t = time.perf_counter()
    try:
        if compare:
            res = generate_best(str(item.photo), item.settings, out_root, jobs=1, force=force)
        else:
            res = generate(str(item.photo), item.settings, out_root, force=force)
        status = "blocked" if res.blocked else "ok"
        msg = ("виробничі файли заблоковано критичними попередженнями" if res.blocked else
               (f"обрано: {res.candidates['selected']['mode']}, {res.candidates['selected']['colors']} кольорів"
                if compare and res.candidates and res.candidates.get("selected") else ""))
        return _row(item, status, msg, res, time.perf_counter() - t)
    except (ZoneError, CatalogError, ProjectError, ValueError) as e:
        return _row(item, "error", str(e), None, time.perf_counter() - t)
    except Exception as e:                           # будь-яка інша помилка одного фото не зупиняє партію
        return _row(item, "error", f"{type(e).__name__}: {e}", None, time.perf_counter() - t)


def run_batch(items: list[BatchItem], out_root: str | Path, jobs: int | None = None, compare: bool = False,
              skip_existing: bool = False, force: bool = False, progress=None, cancel=None) -> list[dict]:
    """Обробляє завдання. progress(done, total, row) викликається в головному процесі після кожного фото;
    cancel() --- чи перервати (фото, що вже виконуються, дообробляються). Рядки повертаються в порядку входу."""
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    rows: dict[int, dict] = {}
    todo: list[int] = []
    for i, it in enumerate(items):
        if it.settings is None:
            rows[i] = _row(it, "error", it.error)
        elif skip_existing and _already_done(out_root, it.order):
            rows[i] = _row(it, "skipped", "пакет уже існує")
        else:
            todo.append(i)
    total, done = len(items), 0
    for i in sorted(rows):
        done += 1
        if progress:
            progress(done, total, rows[i])
    jobs = max(1, min(jobs or min(os.cpu_count() or 1, 4), len(todo) or 1))

    def finish(i: int, row: dict) -> None:
        nonlocal done
        rows[i] = row
        done += 1
        if progress:
            progress(done, total, row)

    if jobs == 1:
        for i in todo:
            if cancel and cancel():
                break
            finish(i, _work((items[i], str(out_root), compare, force)))
    else:
        with cf.ProcessPoolExecutor(max_workers=jobs, mp_context=mp.get_context("spawn")) as ex:
            pending = {ex.submit(_work, (items[i], str(out_root), compare, force)): i for i in todo}
            try:
                for fut in cf.as_completed(pending):
                    finish(pending[fut], fut.result())
                    if cancel and cancel():
                        break
            finally:
                if cancel and cancel():
                    ex.shutdown(wait=True, cancel_futures=True)
    for i, it in enumerate(items):
        if i not in rows:
            rows[i] = _row(it, "cancelled", "перервано оператором")
    return [rows[i] for i in range(len(items))]


def write_report(rows: list[dict], out_root: str | Path, settings: Settings | None = None) -> Path:
    out_root = Path(out_root)
    with open(out_root / "batch_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_COLUMNS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    (out_root / "batch_report.json").write_text(json.dumps({
        "algorithm_version": ALGORITHM_VERSION, "total": len(rows), "counts": counts,
        "base_settings": settings.to_dict() if settings else None, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return out_root / "batch_report.csv"


def exit_code(rows: list[dict]) -> int:
    return 0 if all(r["status"] in ("ok", "skipped") for r in rows) else 2
