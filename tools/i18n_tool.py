"""Службовий інструмент перекладу інтерфейсу (запускається вручну розробником).

  extract : зібрати всі українські рядки (літерали й f-рядки як шаблони з {}) із модулів інтерфейсу -> JSON
  wrap    : обернути кожен такий літерал у tr(...) у модулях GUI (ідемпотентно)

Шаблон f-рядка: кожна підстановка {...} замінюється на {} (специфікації формату відкидаються, бо під час роботи
tr() отримує вже готовий рядок і зіставляє його з шаблоном за регулярним виразом)."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "paint_by_numbers"
CYR = re.compile("[А-Яа-яІіЇїЄєҐґ]")
WRAP_MODULES = ["gui/app.py", "gui/batch_dialog.py", "gui/canvas_view.py", "gui/help_dialog.py", "gui/history.py",
                "gui/main_window.py", "gui/paint_pick.py", "gui/print_dialog.py", "gui/region_editor.py",
                "gui/zone_utils.py"]
EXTRACT_ONLY = ["edit.py", "pipeline/priority_zones.py", "palette/catalog.py", "project.py", "quality/warnings.py",
                "compare.py", "batch.py", "generate.py", "settings.py", "export/package.py"]


def template(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(str(v.value).replace("{", "{{").replace("}", "}}"))
            else:
                out.append("{}")
        return "".join(out)
    return None


def docstring_nodes(tree) -> set[int]:
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.body:
            f = n.body[0]
            if isinstance(f, ast.Expr) and isinstance(f.value, ast.Constant) and isinstance(f.value.value, str):
                ids.add(id(f.value))
    return ids


def candidates(path: Path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    skip = docstring_nodes(tree)
    inside_f: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.JoinedStr):
            for v in ast.walk(n):
                if v is not n:
                    inside_f.add(id(v))
    for n in ast.walk(tree):
        if id(n) in skip or id(n) in inside_f:
            continue
        if isinstance(n, (ast.Constant, ast.JoinedStr)):
            t = template(n)
            if t and CYR.search(t):
                yield n, t


def extract() -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for rel in WRAP_MODULES + EXTRACT_ONLY:
        for n, t in candidates(ROOT / rel):
            keys.setdefault(t, []).append(rel)
    return keys


def wrap() -> int:
    total = 0
    for rel in WRAP_MODULES:
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        wrapped = set()
        for n in ast.walk(tree):                       # уже обгорнуті виклики tr(...)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr":
                for a in n.args:
                    wrapped.add(id(a))
        lines = src.splitlines(keepends=True)
        spans = []
        for n, t in candidates(path):
            if id(n) in wrapped:
                continue
            spans.append((n.lineno, n.col_offset, n.end_lineno, n.end_col_offset))
        spans.sort(reverse=True)
        offs = [0]
        for ln in lines:
            offs.append(offs[-1] + len(ln.encode("utf-8")))
        b = src.encode("utf-8")
        for l0, c0, l1, c1 in spans:                    # зсуви в байтах UTF-8 (ast дає байтові колонки)
            s0, s1 = offs[l0 - 1] + c0, offs[l1 - 1] + c1
            b = b[:s0] + b"tr(" + b[s0:s1] + b")" + b[s1:]
        total += len(spans)
        if spans:
            out = b.decode("utf-8")
            if "from ..i18n import tr" not in out:
                out = _add_import(out)
            path.write_text(out, encoding="utf-8")
    return total


def _add_import(src: str) -> str:
    lines = src.splitlines(keepends=True)
    idx = 0
    for i, ln in enumerate(lines):
        if ln.startswith("from ") or ln.startswith("import "):
            idx = i
    # вставляємо після останнього верхнього імпорту (враховуючи багаторядкові дужки)
    j = idx
    if "(" in lines[j] and ")" not in lines[j]:
        while ")" not in lines[j]:
            j += 1
    lines.insert(j + 1, "from ..i18n import tr\n")
    return "".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "extract"
    if cmd == "extract":
        k = extract()
        Path(sys.argv[2] if len(sys.argv) > 2 else "i18n_keys.json").write_text(
            json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8")
        print(len(k), "ключів")
    elif cmd == "wrap":
        print("обгорнуто:", wrap())
