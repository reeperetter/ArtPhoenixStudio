"""Робота з папками замовлень (ТЗ 15.2, 20): пошук за назвою/номером, список останніх, безпечне видалення."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

MAX_RECENT = 10


class OrderError(Exception):
    pass


def is_order_dir(p: Path) -> bool:
    return p.is_dir() and (p / "project" / "project.json").is_file()


def read_info(folder: str | Path) -> dict | None:
    """Коротка картка замовлення з project.json або None, якщо це не папка проєкту."""
    p = Path(folder)
    if not is_order_dir(p):
        return None
    try:
        meta = json.loads((p / "project" / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return {"folder": str(p), "order_number": str(meta.get("order_number", "")),
            "project_name": str(meta.get("project_name", "")), "created": str(meta.get("created", "")),
            "status": str(meta.get("status", ""))}


def find_orders(root: str | Path, query: str = "", depth: int = 1) -> list[dict]:
    """Шукає замовлення в root і в підпапках до depth рівнів; query --- частина номера, назви чи імені папки.
    Новіші --- першими."""
    root = Path(root)
    found: list[dict] = []

    def walk(d: Path, level: int) -> None:
        try:
            subs = sorted(x for x in d.iterdir() if x.is_dir() and not x.name.startswith("."))
        except OSError:
            return
        for x in subs:
            info = read_info(x)
            if info:
                found.append(info)
            elif level < depth:
                walk(x, level + 1)

    if is_order_dir(root):
        info = read_info(root)
        found = [info] if info else []
    else:
        walk(root, 0)
    q = query.strip().casefold()
    if q:
        found = [i for i in found if q in i["order_number"].casefold() or q in i["project_name"].casefold()
                 or q in Path(i["folder"]).name.casefold()]
    return sorted(found, key=lambda i: i["created"], reverse=True)


def add_recent(recent: list[str], folder: str | Path, limit: int = MAX_RECENT) -> list[str]:
    f = str(Path(folder))
    return ([f] + [r for r in recent if r != f])[:limit]


def parse_recent(raw: str) -> list[str]:
    try:
        v = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [x for x in v if isinstance(x, str)][:MAX_RECENT] if isinstance(v, list) else []


def delete_order(folder: str | Path) -> None:
    """Повністю видаляє папку замовлення (фото, проєкт, пакет). Дозволено лише для справжньої папки
    замовлення: назва order_*, всередині project/project.json; кореневий каталог і домівка заборонені."""
    p = Path(folder).resolve()
    if not p.name.startswith("order_") or not is_order_dir(p):
        raise OrderError("Це не папка замовлення (order_XXXXXX з project/project.json): видалення скасовано.")
    if p == Path.home().resolve() or p.parent == p:
        raise OrderError("Небезпечний шлях: видалення скасовано.")
    shutil.rmtree(p)
