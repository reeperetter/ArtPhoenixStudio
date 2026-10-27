"""Макет попереднього перегляду для клієнта: фото, готова картина, збільшений фрагмент із номерами, склад набору.
Показується покупцеві до оплати/виготовлення. Цін і внутрішніх даних (коди фарб, норми покриття) тут немає."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .pdf import _register_font

DETAIL_MM = (70.0, 42.0)          # розмір фрагмента на полотні, мм
MAX_PNG_SIDE = 1800


def _rgb(bgr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.ascontiguousarray(bgr[..., ::-1]))


def detail_window(res, size_mm=DETAIL_MM) -> tuple[int, int, int, int]:
    """Вікно (x0, y0, x1, y1) у пікселях розбиття з найбільшою кількістю номерів у центральній частині полотна
    (або навколо першої зони пріоритету, якщо вона є)."""
    h, w = res.rm.labels.shape
    ww = min(w, int(round(size_mm[0] * res.px_per_mm)))
    wh = min(h, int(round(size_mm[1] * res.px_per_mm)))
    zones = res.settings.zones
    if zones:
        z = zones[0]
        if z.get("shape") == "polygon" and z.get("points"):
            cx = float(np.mean([p[0] for p in z["points"]]))
            cy = float(np.mean([p[1] for p in z["points"]]))
        elif "cx" in z:
            cx, cy = z["cx"], z["cy"]
        else:
            cx, cy = (z["x0"] + z["x1"]) / 2, (z["y0"] + z["y1"]) / 2
        x0 = int(np.clip(cx * w - ww / 2, 0, w - ww))
        y0 = int(np.clip(cy * h - wh / 2, 0, h - wh))
        return x0, y0, x0 + ww, y0 + wh
    pts = np.array([[s.x, s.y] for s in res.spots if s.digit_px > 0], np.float64).reshape(-1, 2)
    best, best_n = ((w - ww) // 2, (h - wh) // 2), -1
    step = max(1, int(round(min(ww, wh) / 4)))
    for y0 in range(int(0.2 * (h - wh)), int(0.8 * (h - wh)) + 1, step):
        for x0 in range(int(0.2 * (w - ww)), int(0.8 * (w - ww)) + 1, step):
            n = int(((pts[:, 0] >= x0) & (pts[:, 0] < x0 + ww) & (pts[:, 1] >= y0) & (pts[:, 1] < y0 + wh)).sum()) if len(pts) else 0
            if n > best_n:
                best, best_n = (x0, y0), n
    return best[0], best[1], best[0] + ww, best[1] + wh


def before_after_png(original_bgr: np.ndarray, result_bgr: np.ndarray, gap: int = 24) -> np.ndarray:
    h = min(MAX_PNG_SIDE // 2, max(original_bgr.shape[0], result_bgr.shape[0]))
    def fit(img):
        return cv2.resize(img, (int(round(img.shape[1] * h / img.shape[0])), h), interpolation=cv2.INTER_AREA)
    a, b = fit(original_bgr), fit(result_bgr)
    return np.hstack([a, np.full((h, gap, 3), 255, np.uint8), b])


def _fit_box(img_w: float, img_h: float, box_w: float, box_h: float) -> tuple[float, float]:
    s = min(box_w / img_w, box_h / img_h)
    return img_w * s, img_h * s


def write_client_preview(pdf_path: str | Path, png_path: str | Path, res, original_bgr: np.ndarray,
                         store_name: str = "") -> dict:
    font, bold, cyr = _register_font()
    t = (dict(title="Попередній перегляд вашої картини за номерами", photo="Ваше фото", pic="Готова картина",
              detail="Фрагмент контуру з номерами (збільшено)", facts="Склад набору", size="Розмір полотна",
              colors="Кольорів", cont="Ємностей з фарбою", per="по 3 мл", palette="Кольори набору",
              note="Це комп'ютерний попередній перегляд. Кольори фарб і дрібні деталі на готовому наборі можуть "
                   "дещо відрізнятися від зображення на екрані.",
              order="Замовлення", cm="см") if cyr else
         dict(title="Preview of your paint-by-numbers picture", photo="Your photo", pic="Finished picture",
              detail="Outline fragment with numbers (enlarged)", facts="Kit contents", size="Canvas size",
              colors="Colors", cont="Paint containers", per="3 ml each", palette="Kit colors",
              note="This is a computer preview. Paint colors and fine details on the finished kit may differ slightly "
                   "from the on-screen image.", order="Order", cm="cm"))
    s = res.settings
    spec = res.spec
    W, H = A4
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.setTitle(t["title"])
    m = 15 * mm
    y = H - m
    if store_name:
        c.setFont(bold, 11)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(m, y - 4 * mm, store_name)
        y -= 8 * mm
    c.setFillColor(colors.black)
    c.setFont(bold, 17)
    c.drawString(m, y - 6 * mm, t["title"])
    c.setFont(font, 10)
    sub = f'{t["order"]} {s.order_number}' + (f" --- {s.project_name}" if s.project_name else "") + f"  |  {date.today().isoformat()}"
    c.drawString(m, y - 12 * mm, sub)
    y -= 18 * mm

    # фото і картина поруч
    bw = (W - 2 * m - 8 * mm) / 2
    bh = 96 * mm
    for i, (img, cap) in enumerate(((original_bgr, t["photo"]), (res.color_img, t["pic"]))):
        h0, w0 = img.shape[:2]
        dw, dh = _fit_box(w0, h0, bw, bh)
        x = m + i * (bw + 8 * mm) + (bw - dw) / 2
        c.drawImage(ImageReader(_rgb(img)), x, y - dh - 5 * mm, dw, dh)
        c.setStrokeColor(colors.HexColor("#999999"))
        c.rect(x, y - dh - 5 * mm, dw, dh)
        c.setFont(bold, 10)
        c.drawCentredString(m + i * (bw + 8 * mm) + bw / 2, y - 3.5 * mm, cap)
    y -= bh + 10 * mm

    # фрагмент із номерами
    x0, y0, x1, y1 = detail_window(res)
    sc = res.numbered_img.shape[1] / res.rm.labels.shape[1]
    crop = res.numbered_img[int(y0 * sc):int(y1 * sc), int(x0 * sc):int(x1 * sc)]
    c.setFont(bold, 10)
    c.drawString(m, y, t["detail"])
    dw, dh = _fit_box(crop.shape[1], crop.shape[0], W - 2 * m, 52 * mm)
    c.drawImage(ImageReader(_rgb(crop)), m, y - dh - 3 * mm, dw, dh)
    c.setStrokeColor(colors.HexColor("#999999"))
    c.rect(m, y - dh - 3 * mm, dw, dh)
    y -= dh + 11 * mm

    # склад набору
    tot = spec["totals"]
    c.setFont(bold, 10)
    c.drawString(m, y, t["facts"])
    c.setFont(font, 10)
    facts = f'{t["size"]}: {res.width_mm / 10:.0f} × {res.height_mm / 10:.0f} {t["cm"]}   |   {t["colors"]}: {tot["paints"]}'
    if not spec["calculation"]["provisional"]:           # кількість ємностей показуємо лише після підтвердження норми N
        facts += f'   |   {t["cont"]}: {tot["containers"]} ({t["per"]})'
    c.drawString(m, y - 5.5 * mm, facts)
    y -= 12 * mm
    c.setFont(bold, 10)
    c.drawString(m, y, t["palette"])
    sw, per_row = 11 * mm, 12
    for i, p in enumerate(spec["paints"]):
        col, row = i % per_row, i // per_row
        x = m + col * (sw + 4.2 * mm)
        yy = y - 4 * mm - (row + 1) * (sw + 1 * mm) - 3 * mm
        c.setFillColor(colors.HexColor(p["hex"]))
        c.setStrokeColor(colors.HexColor("#777777"))
        c.rect(x, yy + 4 * mm, sw, sw - 4 * mm + 1 * mm, fill=1, stroke=1)
        c.setFillColor(colors.black)
        c.setFont(font, 8)
        c.drawCentredString(x + sw / 2, yy, str(p["number"]))
    rows = (len(spec["paints"]) + per_row - 1) // per_row
    c.setFont(font, 8)
    c.setFillColor(colors.HexColor("#555555"))
    # примітка внизу сторінки, переноситься за шириною
    words, line, lines = t["note"].split(), "", []
    for wd in words:
        if c.stringWidth(line + " " + wd, font, 8) > W - 2 * m:
            lines.append(line)
            line = wd
        else:
            line = (line + " " + wd).strip()
    lines.append(line)
    for i, ln in enumerate(lines):
        c.drawString(m, m + (len(lines) - 1 - i) * 4 * mm, ln)
    c.showPage()
    c.save()
    cv2.imwrite(str(png_path), before_after_png(original_bgr, res.color_img))
    return {"cyrillic_font": cyr, "detail_window_px": [x0, y0, x1, y1]}
