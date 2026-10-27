"""Експорт для друку на замовлення: PDF із припуском (bleed), загортанням на підрамник і мітками різу, растр заданої
роздільної здатності та розбиття на аркуші A4/A3 із перекриттям.

Профіль (`PrintProfile`) універсальний: конкретну друкарню/принтер ще не обрано, тому всі розміри налаштовуються.
Припуск і поле загортання лишаються білими (контур доходить лише до краю полотна): це безпечний варіант, бо друкарня
не отримує «домальованих» елементів. Одиниця в PDF --- мм (1 мм = 2.8346 pt), масштаб 1:1."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .pdf import _register_font, draw_artwork, font_file
from .svg import CAP_HEIGHT_EM

SHEETS = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "A2": (420.0, 594.0)}
SLUG_MM = 8.0                      # поле для міток і службового рядка за припуском
MAX_RASTER_MPIX = 150.0
FORMATS = ("tiff", "png", "none")


class PrintError(ValueError):
    """Некоректний профіль друку (повідомлення зрозуміле оператору)."""


@dataclass
class PrintProfile:
    bleed_mm: float = 5.0           # припуск за лінією обрізу
    wrap_mm: float = 0.0            # додаткове поле під загин на підрамник (з кожного боку)
    marks: bool = True              # мітки різу, позначки країв полотна, службовий рядок
    dpi: int = 300                  # роздільна здатність растру
    raster_format: str = "tiff"     # tiff | png | none
    tiles: str = ""                 # "" (без розбиття), "A4", "A3", "A2" або "ШxВ" у мм
    tile_overlap_mm: float = 10.0   # перекриття сусідніх аркушів
    sheet_margin_mm: float = 8.0    # неприйнятне для друку поле принтера

    @classmethod
    def from_dict(cls, d: dict | None) -> "PrintProfile":
        d = dict(d or {})
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        unknown = set(d) - set(known)
        if unknown:
            raise PrintError(f"Невідомі параметри друку: {', '.join(sorted(unknown))}.")
        p = cls(**known)
        p.validate()
        return p

    def validate(self) -> None:
        def num(name, lo, hi):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                raise PrintError(f"{name}: значення має бути числом від {lo} до {hi}.")
        num("bleed_mm", 0, 20)
        num("wrap_mm", 0, 100)
        num("dpi", 72, 1200)
        num("tile_overlap_mm", 0, 50)
        num("sheet_margin_mm", 0, 30)
        if self.raster_format not in FORMATS:
            raise PrintError(f"raster_format: одне з {', '.join(FORMATS)}.")
        if self.tiles:
            self.sheet_size()

    def sheet_size(self) -> tuple[float, float]:
        t = self.tiles.strip().upper()
        if t in SHEETS:
            return SHEETS[t]
        try:
            w, h = (float(v) for v in t.lower().replace("х", "x").split("x"))
        except ValueError:
            raise PrintError(f"tiles: A4, A3, A2 або ШxВ у мм (наприклад 330x480), отримано «{self.tiles}».")
        if not (100 <= w <= 2000 and 100 <= h <= 2000):
            raise PrintError("tiles: розміри аркуша мають бути від 100 до 2000 мм.")
        return w, h

    def to_dict(self) -> dict:
        return asdict(self)


def load_profile(path: str | Path) -> PrintProfile:
    try:
        return PrintProfile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise PrintError(f"Файл профілю друку не є коректним JSON: {e}")


def raster_size(res, p: PrintProfile) -> tuple[int, int]:
    ppm = p.dpi / 25.4
    m = 2 * (p.bleed_mm + p.wrap_mm)
    return int(round((res.width_mm + m) * ppm)), int(round((res.height_mm + m) * ppm))


# ------------------------------------------------------------------ PDF для друкарні
def _crop_marks(c, x0, y0, x1, y1, bleed):
    """Мітки різу в кутах прямокутника обрізу (x0,y0)-(x1,y1), мм."""
    off, ln = bleed + 1.5, 5.0
    c.setLineWidth(0.25)
    c.setStrokeColorRGB(0, 0, 0)
    for x, sx in ((x0, -1), (x1, 1)):
        for y, sy in ((y0, -1), (y1, 1)):
            c.line((x + sx * off) * mm, y * mm, (x + sx * (off + ln)) * mm, y * mm)
            c.line(x * mm, (y + sy * off) * mm, x * mm, (y + sy * (off + ln)) * mm)


def write_print_pdf_with_bleed(path: str | Path, res, p: PrintProfile, title: str) -> dict:
    font, _, cyr = _register_font()
    W, H = res.width_mm, res.height_mm
    trim_w, trim_h = W + 2 * p.wrap_mm, H + 2 * p.wrap_mm
    slug = (SLUG_MM + p.bleed_mm) if p.marks else p.bleed_mm
    pw, ph = trim_w + 2 * slug, trim_h + 2 * slug
    c = canvas.Canvas(str(path), pagesize=(pw * mm, ph * mm), pageCompression=1, initialFontName=font)
    c.setTitle(title)
    c.setCreator("paint-by-numbers")
    tx0, ty0 = slug, slug
    tx1, ty1 = slug + trim_w, slug + trim_h
    for name, (a, b, cc, d) in (("setTrimBox", (tx0, ty0, tx1, ty1)),
                                ("setBleedBox", (tx0 - p.bleed_mm, ty0 - p.bleed_mm, tx1 + p.bleed_mm, ty1 + p.bleed_mm))):
        if hasattr(c, name):
            getattr(c, name)((a * mm, b * mm, cc * mm, d * mm))
    n = draw_artwork(c, res.geom, res.spots, res.px_per_mm, H, res.line_mm, font, tx0 + p.wrap_mm, ty0 + p.wrap_mm)
    if p.marks:
        _crop_marks(c, tx0, ty0, tx1, ty1, p.bleed_mm)
        if p.wrap_mm > 0:                  # позначки країв лицьової сторони полотна (для загину)
            c.setLineWidth(0.25)
            c.setStrokeColorRGB(0, 0, 0)
            fx0, fy0, fx1, fy1 = tx0 + p.wrap_mm, ty0 + p.wrap_mm, tx1 - p.wrap_mm, ty1 - p.wrap_mm
            top, left = ph - 3.5, 3.5
            for x in (fx0, fx1):
                c.line(x * mm, (top - 2.5) * mm, x * mm, (top + 2.5) * mm)
            for y in (fy0, fy1):
                c.line((left - 2.5) * mm, y * mm, (left + 2.5) * mm, y * mm)
        c.setFont(font, 6.5)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        info = (f'{"Замовлення" if cyr else "Order"} {res.settings.order_number} | {W:.0f} x {H:.0f} mm | '
                f'bleed {p.bleed_mm:g} mm | wrap {p.wrap_mm:g} mm | 1:1 | {date.today().isoformat()}')
        c.drawString((tx0 + 2) * mm, 2.2 * mm, info)
    c.showPage()
    c.save()
    return {"page_mm": [round(pw, 2), round(ph, 2)], "trim_mm": [trim_w, trim_h], "numbers": n,
            "font_embedded": font != "Helvetica"}


# ------------------------------------------------------------------ растр
def write_print_raster(path: str | Path, res, p: PrintProfile) -> dict:
    wpx, hpx = raster_size(res, p)
    if wpx * hpx / 1e6 > MAX_RASTER_MPIX:
        raise PrintError(f"Растр {wpx}x{hpx} ({wpx * hpx / 1e6:.0f} Мпікс) завеликий: зменште dpi "
                         f"(межа {MAX_RASTER_MPIX:.0f} Мпікс).")
    ppm = p.dpi / 25.4
    s = ppm / res.px_per_mm                    # пікселів растру на піксель розбиття
    off = (p.bleed_mm + p.wrap_mm) * ppm
    img = np.full((hpx, wpx), 255, np.uint8)
    th = max(1, int(round(res.line_mm * ppm)))
    for ch in res.geom.chains:
        pts = np.round((ch.pts * s + off) * 16).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [pts], bool(ch.closed), 0, th, cv2.LINE_AA, shift=4)
    gray = 51
    lead_th = max(1, int(round(res.line_mm * 0.5 * ppm)))
    for sp in res.spots:
        if sp.digit_px <= 0 or sp.anchor is None:
            continue
        a = np.array(sp.anchor) * s + off
        b = np.array(sp.lead_from) * s + off
        cv2.line(img, tuple(int(round(v)) for v in b), tuple(int(round(v)) for v in a), gray, lead_th, cv2.LINE_AA)
        cv2.circle(img, tuple(int(round(v)) for v in a), max(1, int(round(res.line_mm * 0.8 * ppm))), gray, -1, cv2.LINE_AA)
    im = Image.fromarray(img)
    del img
    d = ImageDraw.Draw(im)
    ff = font_file()
    fonts: dict[int, ImageFont.FreeTypeFont] = {}
    for sp in res.spots:
        if sp.digit_px <= 0:
            continue
        h_px = sp.digit_px * s
        size = max(2, int(round(h_px / CAP_HEIGHT_EM)))
        x, y = sp.x * s + off, sp.y * s + off
        if ff:
            f = fonts.setdefault(size, ImageFont.truetype(ff, size))
            d.text((x, y + h_px / 2), str(sp.number), fill=gray, font=f, anchor="ms")
        else:                                  # без шрифта: вбудований растровий (запасний варіант)
            d.text((x, y), str(sp.number), fill=gray, anchor="mm")
    kw = {"dpi": (p.dpi, p.dpi)}
    if p.raster_format == "tiff":
        im.save(path, format="TIFF", compression="tiff_lzw", **kw)
    else:
        im.save(path, format="PNG", **kw)
    return {"width_px": wpx, "height_px": hpx, "dpi": p.dpi, "format": p.raster_format}


# ------------------------------------------------------------------ розбиття на аркуші
def plan_tiles(trim_w: float, trim_h: float, sheet: tuple[float, float], margin: float, overlap: float):
    """Обирає орієнтацію аркуша з найменшою кількістю аркушів. Повертає (орієнтація, pw, ph, xs, ys), де xs, ys ---
    лівий/нижній край кожної плитки у координатах області друку (мм); ys впорядковано зверху вниз."""
    best = None
    for landscape in (False, True):
        sw, sh = (sheet[1], sheet[0]) if landscape else sheet
        pw, ph = sw - 2 * margin, sh - 2 * margin
        if pw <= overlap or ph <= overlap:
            raise PrintError("Аркуш замалий для вказаних поля й перекриття.")
        def axis(total, size):
            if total <= size:
                return [0.0]
            n = math.ceil((total - overlap) / (size - overlap) - 1e-9)
            return [float(v) for v in np.linspace(0.0, total - size, n)]      # рівномірно: перекриття не менше заданого
        xs, ys = axis(trim_w, pw), axis(trim_h, ph)
        cand = (len(xs) * len(ys), landscape, sw, sh, pw, ph, xs, ys)
        if best is None or cand[:2] < best[:2]:
            best = cand
    _, landscape, sw, sh, pw, ph, xs, ys = best
    ys = sorted(ys, reverse=True)              # перший рядок --- верхній
    return landscape, sw, sh, pw, ph, xs, ys


def write_tiled_pdf(path: str | Path, res, p: PrintProfile, title: str) -> dict:
    font, bold, cyr = _register_font()
    W, H = res.width_mm, res.height_mm
    trim_w, trim_h = W + 2 * p.wrap_mm, H + 2 * p.wrap_mm
    landscape, sw, sh, pw, ph, xs, ys = plan_tiles(trim_w, trim_h, p.sheet_size(), p.sheet_margin_mm, p.tile_overlap_mm)
    mg, ov = p.sheet_margin_mm, p.tile_overlap_mm
    nx, ny = len(xs), len(ys)
    c = canvas.Canvas(str(path), pagesize=(sw * mm, sh * mm), pageCompression=1, initialFontName=font)
    c.setTitle(title)
    c.setCreator("paint-by-numbers")
    T = (dict(index="Схема складання", sheet="Аркуш", of="з", row="ряд", col="колонка", glue="перекриття: склеїти",
              order="Замовлення", hint=f"Друкуйте без масштабування (100 %). Аркуші накладаються на {ov:g} мм: "
                                       "суміщайте контури, обріжте поля й склейте. Нумерація: ряд-колонка.")
         if cyr else dict(index="Assembly layout", sheet="Sheet", of="of", row="row", col="col", glue="overlap: glue",
                          order="Order", hint=f"Print at 100% scale. Sheets overlap by {ov:g} mm."))
    # сторінка-схема
    c.setFont(bold, 14)
    c.drawString(mg * mm, (sh - mg - 6) * mm, f'{T["index"]}: {T["order"]} {res.settings.order_number}')
    c.setFont(font, 9)
    c.drawString(mg * mm, (sh - mg - 13) * mm, f"{trim_w:.0f} x {trim_h:.0f} mm; {nx} x {ny} = {nx * ny}")
    box_w, box_h = sw - 2 * mg, sh - 2 * mg - 40
    k = min(box_w / trim_w, box_h / trim_h)
    gx0, gy0 = mg + (box_w - trim_w * k) / 2, mg + 10
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.rect(gx0 * mm, gy0 * mm, trim_w * k * mm, trim_h * k * mm)
    num = 0
    for r, y0 in enumerate(ys):
        for cidx, x0 in enumerate(xs):
            num += 1
            rx, ry = gx0 + x0 * k, gy0 + y0 * k
            c.setStrokeColorRGB(0.1, 0.4, 0.8)
            c.setDash(2, 2)
            c.rect(rx * mm, ry * mm, pw * k * mm, ph * k * mm)
            c.setDash()
            c.setFont(bold, 10)
            c.setFillColorRGB(0.1, 0.4, 0.8)
            c.drawCentredString((rx + pw * k / 2) * mm, (ry + ph * k / 2 - 1.5) * mm, f"{num}  ({r + 1}-{cidx + 1})")
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.setFont(font, 8)
    c.drawString(mg * mm, mg * mm, T["hint"])
    c.showPage()
    # плитки
    num = 0
    for r, y0 in enumerate(ys):
        for cidx, x0 in enumerate(xs):
            num += 1
            c.saveState()
            clip = c.beginPath()
            clip.rect(mg * mm, mg * mm, pw * mm, ph * mm)
            c.clipPath(clip, stroke=0, fill=0)
            draw_artwork(c, res.geom, res.spots, res.px_per_mm, H, res.line_mm, font,
                         mg - x0 + p.wrap_mm, mg - y0 + p.wrap_mm)
            c.restoreState()
            c.setLineWidth(0.25)
            c.setStrokeColorRGB(0.5, 0.5, 0.5)
            for x, y in ((mg, mg), (mg + pw, mg), (mg, mg + ph), (mg + pw, mg + ph)):     # кутові хрестики
                c.line((x - 3) * mm, y * mm, (x + 3) * mm, y * mm)
                c.line(x * mm, (y - 3) * mm, x * mm, (y + 3) * mm)
            c.setDash(1.5, 1.5)
            if cidx > 0:
                c.line((mg + ov) * mm, mg * mm, (mg + ov) * mm, (mg + ph) * mm)
            if cidx < nx - 1:
                c.line((mg + pw - ov) * mm, mg * mm, (mg + pw - ov) * mm, (mg + ph) * mm)
            if r > 0:
                c.line(mg * mm, (mg + ph - ov) * mm, (mg + pw) * mm, (mg + ph - ov) * mm)
            if r < ny - 1:
                c.line(mg * mm, (mg + ov) * mm, (mg + pw) * mm, (mg + ov) * mm)
            c.setDash()
            c.setFont(font, 7)
            c.setFillColorRGB(0.35, 0.35, 0.35)
            c.drawString(mg * mm, (mg - 4) * mm if mg >= 5 else 1 * mm,
                         f'{T["order"]} {res.settings.order_number} | {T["sheet"]} {num} {T["of"]} {nx * ny} '
                         f'({T["row"]} {r + 1}, {T["col"]} {cidx + 1}) | {T["glue"]} {ov:g} mm')
            c.showPage()
    c.save()
    return {"sheets": nx * ny, "columns": nx, "rows": ny, "sheet_mm": [sw, sh], "landscape": landscape}


# ------------------------------------------------------------------ усе разом
def write_print_ready(out_dir: str | Path, res, p: PrintProfile) -> dict[str, dict]:
    """Створює файли в out_dir. Повертає {відносне імʼя: відомості}."""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    p.validate()
    title = f"{res.settings.project_name or 'Order'} {res.settings.order_number} (print)"
    out: dict[str, dict] = {}
    out["canvas_print_ready.pdf"] = write_print_pdf_with_bleed(d / "canvas_print_ready.pdf", res, p, title)
    if p.raster_format != "none":
        ext = "tif" if p.raster_format == "tiff" else "png"
        name = f"canvas_print_ready_{p.dpi}dpi.{ext}"
        out[name] = write_print_raster(d / name, res, p)
    if p.tiles:
        name = f"canvas_tiles_{p.tiles.strip().upper().replace(' ', '')}.pdf"
        out[name] = write_tiled_pdf(d / name, res, p, title)
    (d / "print_profile.json").write_text(json.dumps(p.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    out["print_profile.json"] = {}
    return out
