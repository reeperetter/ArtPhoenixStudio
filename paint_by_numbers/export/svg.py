"""Векторний контурний макет (SVG) у міліметрах. Кожна спільна межа записана один раз (розділ 12.3 ТЗ)."""
from __future__ import annotations

from pathlib import Path

from ..geometry.labels import NumberSpot
from ..geometry.planar import Geometry

CAP_HEIGHT_EM = 0.716      # висота цифри відносно розміру шрифту (Arial/Helvetica)


def write_svg(path: str | Path, geom: Geometry, spots: list[NumberSpot], px_per_mm: float,
              width_mm: float, height_mm: float, line_mm: float, line_color: str = "#000000",
              number_color: str = "#333333") -> dict:
    s = 1.0 / px_per_mm
    d = []
    for ch in geom.chains:
        p = ch.pts * s
        seg = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in p)
        if ch.closed:
            seg += " Z"
        d.append(seg)
    texts = []
    leads = []
    for sp in spots:
        if sp.digit_px <= 0:
            continue
        if sp.anchor is not None:
            leads.append(f'<line x1="{sp.lead_from[0] * s:.2f}" y1="{sp.lead_from[1] * s:.2f}" '
                         f'x2="{sp.anchor[0] * s:.2f}" y2="{sp.anchor[1] * s:.2f}"/>')
            leads.append(f'<circle cx="{sp.anchor[0] * s:.2f}" cy="{sp.anchor[1] * s:.2f}" r="{line_mm * 0.8:.2f}" '
                         f'stroke="none"/>')
        h_mm = sp.digit_px * s
        fs = h_mm / CAP_HEIGHT_EM
        texts.append(
            f'<text x="{sp.x * s:.2f}" y="{sp.y * s + h_mm / 2:.2f}" font-size="{fs:.2f}">{sp.number}</text>'
        )
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.2f}mm" height="{height_mm:.2f}mm" '
        f'viewBox="0 0 {width_mm:.4f} {height_mm:.4f}">\n'
        f'<path id="contours" d="{" ".join(d)}" fill="none" stroke="{line_color}" '
        f'stroke-width="{line_mm:.3f}" stroke-linecap="round" stroke-linejoin="round"/>\n'
        f'<g id="leaders" stroke="{number_color}" stroke-width="{line_mm * 0.5:.3f}" fill="{number_color}">\n'
        + "\n".join(leads) + "\n</g>\n"
        f'<g id="numbers" font-family="Arial, Helvetica, sans-serif" text-anchor="middle" '
        f'fill="{number_color}">\n' + "\n".join(texts) + "\n</g>\n</svg>\n"
    )
    Path(path).write_text(svg, encoding="utf-8")
    return {"paths": len(d), "numbers": len(texts), "leaders": len(leads) // 2, "bytes": len(svg.encode("utf-8"))}
