"""PDF: друкований контурний макет у фізичних розмірах і виробнича специфікація (розділ 12.4, 11 ТЗ)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..geometry.labels import NumberSpot
from ..geometry.planar import Geometry
from .svg import CAP_HEIGHT_EM

# Кирилиця в специфікації потребує TTF-шрифта. Шукаємо у типових місцях; якщо шрифта немає,
# специфікація друкується англійською стандартним Helvetica (розділ 25 ТЗ: шрифт для поставки
# потрібно вибрати й перевірити за ліцензією).
def resource_dir() -> Path:
    """Папка ресурсів пакета; у зібраній програмі (PyInstaller) --- тимчасова папка розпакування."""
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) / "paint_by_numbers") if base else Path(__file__).resolve().parent.parent


_BUNDLED = resource_dir() / "assets" / "fonts"

# Шрифт DejaVu Sans іде разом із програмою (ліцензія Bitstream Vera/DejaVu дозволяє поширення з
# умовою зберегти текст ліцензії: assets/fonts/LICENSE-DejaVu.txt), тож кирилиця в PDF працює скрізь.
_FONT_CANDIDATES = [
    ("PBN-Sans", str(_BUNDLED / "DejaVuSans.ttf"), str(_BUNDLED / "DejaVuSans-Bold.ttf")),
    ("PBN-Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("PBN-Sans", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("PBN-Sans", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("PBN-Sans", "/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("PBN-Sans", "/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]


def _register_font() -> tuple[str, str, bool]:
    env = os.environ.get("PBN_FONT")
    cands = ([("PBN-Sans", env, env)] if env else []) + _FONT_CANDIDATES
    for name, reg, bold in cands:
        if reg and Path(reg).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, reg))
                bname = name + "-Bold"
                pdfmetrics.registerFont(TTFont(bname, bold if bold and Path(bold).exists() else reg))
                return name, bname, True
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold", False


def font_file() -> str | None:
    """Шлях до звичайного TTF-шрифта, яким друкуються номери (той самий, що вбудовується в PDF)."""
    env = os.environ.get("PBN_FONT")
    for _name, reg, _bold in ([("PBN-Sans", env, env)] if env else []) + _FONT_CANDIDATES:
        if reg and Path(reg).exists():
            return reg
    return None


def draw_artwork(c, geom: Geometry, spots: list[NumberSpot], px_per_mm: float, height_mm: float, line_mm: float,
                 font: str, ox_mm: float = 0.0, oy_mm: float = 0.0) -> int:
    """Малює контури й номери на сторінці PDF; (ox_mm, oy_mm) --- зсув лівого нижнього кута полотна на сторінці.
    Повертає кількість надрукованих номерів."""
    s = 1.0 / px_per_mm
    c.saveState()
    c.translate(ox_mm * mm, oy_mm * mm)
    c.setLineWidth(line_mm * mm)
    c.setLineCap(1)
    c.setLineJoin(1)
    c.setStrokeColorRGB(0, 0, 0)
    p = c.beginPath()
    for ch in geom.chains:
        pts = ch.pts * s
        p.moveTo(pts[0, 0] * mm, (height_mm - pts[0, 1]) * mm)
        for x, y in pts[1:]:
            p.lineTo(x * mm, (height_mm - y) * mm)
        if ch.closed:
            p.close()
    c.drawPath(p, stroke=1, fill=0)
    c.setFillColorRGB(0.2, 0.2, 0.2)
    n = 0
    for sp in spots:
        if sp.digit_px <= 0:
            continue
        if sp.anchor is not None:
            c.setStrokeColorRGB(0.2, 0.2, 0.2)
            c.setLineWidth(line_mm * 0.5 * mm)
            c.line(sp.lead_from[0] * s * mm, (height_mm - sp.lead_from[1] * s) * mm,
                   sp.anchor[0] * s * mm, (height_mm - sp.anchor[1] * s) * mm)
            c.circle(sp.anchor[0] * s * mm, (height_mm - sp.anchor[1] * s) * mm, line_mm * 0.8 * mm,
                     stroke=0, fill=1)
        h_mm = sp.digit_px * s
        c.setFont(font, h_mm / CAP_HEIGHT_EM * mm)
        c.drawCentredString(sp.x * s * mm, (height_mm - sp.y * s - h_mm / 2) * mm, str(sp.number))
        n += 1
    c.restoreState()
    return n


def write_print_pdf(path: str | Path, geom: Geometry, spots: list[NumberSpot], px_per_mm: float,
                    width_mm: float, height_mm: float, line_mm: float, title: str) -> dict:
    """Сторінка дорівнює полотну: 1 одиниця = 1 мм, без полів і масштабування."""
    font, _, _ = _register_font()          # шрифт вбудовується у файл (розділ 12.4 ТЗ)
    c = canvas.Canvas(str(path), pagesize=(width_mm * mm, height_mm * mm), pageCompression=1,
                      initialFontName=font)
    c.setTitle(title)
    c.setCreator("ArtPhoenix Studio")
    n = draw_artwork(c, geom, spots, px_per_mm, height_mm, line_mm, font)
    c.showPage()
    c.save()
    return {"width_mm": width_mm, "height_mm": height_mm, "numbers": n, "font_embedded": font != "Helvetica"}


_L = {
    "uk": dict(title="Виробнича специфікація", order="Замовлення", canvas="Полотно", mode="Режим",
               colors="Кольорів", num="№", code="Код фарби", color="Колір", hexc="HEX", area="Площа, мм²",
               regions="Ділянок", cont="Ємностей", vol="Об'єм, мл", total="Разом", unit="мм", cm="мл",
               warn="Попередження", none="Немає", provisional="ОРІЄНТОВНИЙ РОЗРАХУНОК",
               formula="Формула", cover="Норма покриття N (мм²/ємність)", unset="не задано", k="Коефіцієнт запасу K",
               one="Номінальний об'єм однієї ємності"),
    "en": dict(title="Production specification", order="Order", canvas="Canvas", mode="Mode",
               colors="Colors", num="No.", code="Paint code", color="Color", hexc="HEX", area="Area, mm2",
               regions="Regions", cont="Containers", vol="Volume, ml", total="Total", unit="mm", cm="ml",
               warn="Warnings", none="None", provisional="PROVISIONAL CALCULATION",
               formula="Formula", cover="Coverage N (mm2/container)", unset="not set", k="Safety factor K",
               one="Nominal volume of one container"),
}


from ..settings import MODE_NAMES_EN as _EN, MODE_NAMES_UK as _UK
_MODES = {True: {k: v.split(". ", 1)[-1] for k, v in _UK.items()}, False: dict(_EN)}


def write_spec_pdf(path: str | Path, spec: dict, meta: dict, warnings: list[dict]) -> dict:
    font, bold, cyr = _register_font()
    t = _L["uk" if cyr else "en"]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm, title=t["title"], author="reeperetter")
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=16, spaceAfter=4)
    nm = ParagraphStyle("nm", fontName=font, fontSize=9.5, leading=13)
    small = ParagraphStyle("sm", fontName=font, fontSize=8.5, leading=11, textColor=colors.HexColor("#444444"))
    warn_style = ParagraphStyle("wr", fontName=bold, fontSize=10, textColor=colors.HexColor("#B00020"), spaceBefore=4)

    flow = [Paragraph(t["title"], h1)]
    name = f' --- {meta["project_name"]}' if meta.get("project_name") else ""
    flow.append(Paragraph(f'{t["order"]}: {meta["order_number"]}{name}', nm))
    flow.append(Paragraph(f'{t["canvas"]}: {meta["width_mm"]:.0f} x {meta["height_mm"]:.0f} {t["unit"]}; '
                          f'{t["mode"]}: {_MODES[cyr].get(meta["mode"], meta["mode"])}; {t["colors"]}: {spec["totals"]["paints"]}', nm))
    calc = spec["calculation"]
    cov = calc["coverage_mm2_per_container_N"]
    flow.append(Paragraph(f'{t["one"]}: {meta["container_ml"]:g} {t["cm"]}. {t["formula"]}: {calc["formula"]}; '
                          f'{t["cover"]} = {cov if cov else t["unset"]}; {t["k"]} = {calc["safety_factor_K"]}', small))
    if calc["provisional"]:
        flow.append(Paragraph(t["provisional"], warn_style))
        if cyr:
            flow.append(Paragraph(calc["note"], small))
    flow.append(Spacer(1, 6 * mm))

    head = [t["num"], t["code"], t["color"], t["hexc"], t["area"], t["regions"], t["cont"], t["vol"]]
    rows = [head]
    for p in spec["paints"]:
        rows.append([p["number"], p["paint_code"] + (f'\n{p["paint_name"]}' if p["paint_name"] else ""), "", p["hex"], f'{p["area_mm2"]:,.0f}'.replace(",", " "),
                     p["regions"], p["containers"], f'{p["total_ml"]:g}'])
    tot = spec["totals"]
    rows.append([t["total"], "", "", "", f'{tot["canvas_area_mm2"]:,.0f}'.replace(",", " "),
                 sum(p["regions"] for p in spec["paints"]), tot["containers"], f'{tot["total_ml"]:g}'])
    tbl = Table(rows, colWidths=[12 * mm, 40 * mm, 18 * mm, 20 * mm, 26 * mm, 16 * mm, 20 * mm, 18 * mm], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), bold), ("FONTNAME", (0, -1), (-1, -1), bold),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6ECF5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("TOPPADDING", (0, 1), (-1, -1), 4), ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]
    for i, p in enumerate(spec["paints"], start=1):
        style.append(("BACKGROUND", (2, i), (2, i), colors.HexColor(p["hex"])))
    tbl.setStyle(TableStyle(style))
    flow.append(tbl)

    shown = [w for w in warnings if w["severity"] != "info"]
    flow.append(Spacer(1, 6 * mm))
    flow.append(Paragraph(f'{t["warn"]}:', ParagraphStyle("wh", fontName=bold, fontSize=10)))
    if shown and cyr:
        for w in shown:
            flow.append(Paragraph(f'[{w["severity"]}] {w["code"]}: {w["message"]}', small))
    elif shown:
        for w in shown:
            flow.append(Paragraph(f'[{w["severity"]}] {w["code"]}', small))
    else:
        flow.append(Paragraph(t["none"], small))
    doc.build(flow)
    return {"cyrillic_font": cyr}
