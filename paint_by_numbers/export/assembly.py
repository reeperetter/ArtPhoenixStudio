"""Лист складання набору для працівника, що комплектує замовлення: що покласти в коробку, скільки яких ємностей
відібрати, що перевірити перед пакуванням. Друкується на A4 (1--2 сторінки), із полями для відміток і підписів."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .pdf import _register_font

BOX = "☐"          # U+2610; у DejaVu Sans є

# Типовий комплект. Склад і кількості --- гіпотеза до запуску виробництва: змінюється файлом --kit-items.
DEFAULT_KIT_ITEMS = [
    {"name": "Полотно з нанесеним контуром і номерами", "qty": 1},
    {"name": "Пензлик", "qty": 3},
    {"name": "Картка з нумерацією кольорів (аркуш палітри)", "qty": 1},
]

QC_ITEMS = [
    "Контур і номери на полотні чіткі, без плям і зсуву",
    "Кількість різних кольорів на полотні збігається з таблицею",
    "Усі ємності закриті, кришки не протікають, колір відповідає зразку",
    "Кількість ємностей кожного кольору збігається з таблицею; зайвих немає",
    "Номер замовлення на коробці й на аркуші палітри однаковий",
]

L_EN = dict(title="Kit assembly sheet", order="Order", canvas="Canvas", date="Date", items="Kit contents", item="Item",
            qty="Qty", ok="OK", paints="Paint containers", num="No.", color="Color", code="Code", cont="Containers",
            ml="ml", picked="Picked", checked="Checked", qc="Quality check before packing", sign="Assembled by",
            sign2="Checked by", total="Total", prov="PROVISIONAL: container counts are estimates (coverage norm not confirmed).",
            many="many containers of one color: check all are the same batch")


def load_kit_items(path: str | Path | None) -> list[dict]:
    if not path:
        return [dict(i) for i in DEFAULT_KIT_ITEMS]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    out = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict) or not str(it.get("name", "")).strip():
            raise ValueError(f"Позиція комплекту №{i}: потрібне поле «name».")
        q = it.get("qty", 1)
        if not isinstance(q, int) or q < 1:
            raise ValueError(f"Позиція «{it['name']}»: qty має бути цілим числом >= 1.")
        out.append({"name": str(it["name"]), "qty": q})
    if not out:
        raise ValueError("Склад комплекту порожній.")
    return out


def write_assembly_pdf(path: str | Path, spec: dict, meta: dict, kit_items: list[dict] | None = None,
                       many_threshold: int = 4) -> dict:
    font, bold, cyr = _register_font()
    items = kit_items or DEFAULT_KIT_ITEMS
    t = (dict(title="Лист складання набору", order="Замовлення", canvas="Полотно", date="Дата", items="Комплектація",
              item="Позиція", qty="К-сть", ok="Є", paints="Ємності з фарбою", num="№", color="Колір", code="Код / назва",
              cont="Ємностей", ml="мл", picked="Відібрано", checked="Перевірено", qc="Контроль перед пакуванням",
              sign="Склав (підпис)", sign2="Перевірив (підпис)", total="Разом",
              prov="ОРІЄНТОВНО: кількість ємностей попередня (норму покриття ще не підтверджено).",
              many="багато ємностей одного кольору: переконайтеся, що всі з однієї партії") if cyr else L_EN)
    box = BOX if cyr else "[ ]"
    qc = QC_ITEMS if cyr else ["Outline and numbers are clear", "Number of colors matches the table",
                               "All containers closed, color matches", "Container counts match the table",
                               "Order number on box and palette sheet match"]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=t["title"], author="reeperetter")
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=17, leading=22, spaceAfter=4)
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=11, spaceBefore=8, spaceAfter=3)
    nm = ParagraphStyle("nm", fontName=font, fontSize=10, leading=13)
    small = ParagraphStyle("sm", fontName=font, fontSize=8.5, leading=11, textColor=colors.HexColor("#444444"))
    warn = ParagraphStyle("w", fontName=bold, fontSize=10, textColor=colors.HexColor("#B00020"), spaceBefore=3)
    name = f' --- {meta["project_name"]}' if meta.get("project_name") else ""
    tot = spec["totals"]
    flow = [Paragraph(t["title"], h1),
            Paragraph(f'<b>{t["order"]}: {meta["order_number"]}</b>{name}', nm),
            Paragraph(f'{t["canvas"]}: {meta["width_mm"]:.0f} x {meta["height_mm"]:.0f} мм; {t["date"]}: '
                      f'{date.today().isoformat()}' if cyr else
                      f'{t["canvas"]}: {meta["width_mm"]:.0f} x {meta["height_mm"]:.0f} mm; {t["date"]}: {date.today().isoformat()}', nm)]
    if spec["calculation"]["provisional"]:
        flow.append(Paragraph(t["prov"], warn))

    flow.append(Paragraph(t["items"], h2))
    rows = [[t["item"], t["qty"], t["ok"]]]
    for it in items:
        rows.append([Paragraph(it["name"], nm), it["qty"], box])
    rows.append([Paragraph(f'{t["paints"]} ({tot["paints"]})', nm), tot["containers"], box])
    k = Table(rows, colWidths=[132 * mm, 22 * mm, 22 * mm])
    k.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("FONTNAME", (0, 0), (-1, 0), bold), ("FONTSIZE", (0, 0), (-1, -1), 10),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6ECF5")), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    flow.append(k)

    flow.append(Paragraph(f'{t["paints"]}: {tot["containers"]} ({tot["total_ml"]:g} {t["ml"]})', h2))
    head = [t["num"], t["color"], t["code"], t["cont"], t["ml"], t["picked"], t["checked"]]
    rows, many = [head], []
    for p in spec["paints"]:
        label = p["paint_code"] + (f'\n{p["paint_name"]}' if p["paint_name"] else "")
        rows.append([p["number"], "", Paragraph(label.replace("\n", "<br/>"), nm), p["containers"], f'{p["total_ml"]:g}', box, box])
        if p["containers"] >= many_threshold:
            many.append(len(rows) - 1)
    tb = Table(rows, colWidths=[12 * mm, 16 * mm, 54 * mm, 22 * mm, 16 * mm, 28 * mm, 28 * mm], repeatRows=1)
    st = [("FONTNAME", (0, 0), (-1, -1), font), ("FONTNAME", (0, 0), (-1, 0), bold), ("FONTSIZE", (0, 0), (-1, -1), 10),
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6ECF5")), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
          ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("FONTSIZE", (3, 1), (3, -1), 13), ("FONTNAME", (3, 1), (3, -1), bold),
          ("TOPPADDING", (0, 1), (-1, -1), 5), ("BOTTOMPADDING", (0, 1), (-1, -1), 5)]
    for i, p in enumerate(spec["paints"], 1):
        st.append(("BACKGROUND", (1, i), (1, i), colors.HexColor(p["hex"])))
    for r in many:
        st.append(("BACKGROUND", (3, r), (3, r), colors.HexColor("#FFF2CC")))
    tb.setStyle(TableStyle(st))
    flow.append(tb)
    if many:
        flow.append(Paragraph(f'<b>{t["cont"]}</b> ≥ {many_threshold}: {t["many"]}.', small))

    qcb = [Paragraph(t["qc"], h2)] + [Paragraph(f"{box}&nbsp;&nbsp;{q}", nm) for q in qc]
    sign = Table([[f'{t["sign"]}: ______________________', f'{t["sign2"]}: ______________________']],
                 colWidths=[88 * mm, 88 * mm])
    sign.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 14)]))
    flow.append(KeepTogether(qcb + [Spacer(1, 3 * mm), sign]))
    doc.build(flow)
    return {"cyrillic_font": cyr, "items": len(items)}
