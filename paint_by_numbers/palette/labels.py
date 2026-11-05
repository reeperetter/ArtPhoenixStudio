"""Підписи фарб для PDF і етикеток."""
from __future__ import annotations


def label_lines(p: dict) -> list[str]:
    """Рядки підпису фарби для PDF/етикеток: код, назва (або рецепт змішування по рядку на компонент), пігменти."""
    if p.get("mix"):
        def f(v):
            return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return [p["paint_code"]] + [f'{c["name"] or c["code"]}: {f(c["ml_per_container"])} мл' for c in p["mix"]["components"]]
    lines = [p["paint_code"]]
    if p["paint_name"]:
        lines.append(p["paint_name"])
    if p.get("pigments"):
        lines.append(" + ".join(p["pigments"]))
    return lines
