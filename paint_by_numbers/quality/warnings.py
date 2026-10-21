"""Система попереджень (розділ 13.6 ТЗ): код, опис, серйозність, ділянки, рекомендація."""
from __future__ import annotations

CRITICAL, WARNING, INFO = "critical", "warning", "info"


def _w(code, severity, message, recommendation, regions=None):
    d = {"code": code, "severity": severity, "message": message, "recommendation": recommendation}
    if regions:
        d["regions"] = list(regions)[:50]
        d["regions_total"] = len(list(regions))
    return d


def collect(img_warnings: list[dict], geom_topology: dict, spots, region_area_mm2, settings, spec,
            colors_requested: int, colors_final: int, px_per_mm: float, zone_report: dict | None = None) -> list[dict]:
    p = settings.preset
    out: list[dict] = list(img_warnings)

    if not geom_topology["ok"]:
        out.append(_w("GEO_TOPOLOGY", CRITICAL, "Перевірка топології не пройдена (щілини, накладання або "
                      "некоректні грані).", "Повторіть генерацію з іншими налаштуваннями; макет не можна "
                      "передавати у виробництво.")) 

    nr = [s.region for s in spots if s.digit_px <= 0]
    if nr:
        out.append(_w("NUM_NO_ROOM", WARNING, f"{len(nr)} ділянок без місця для номера.",
                      "Зменште кількість кольорів, оберіть режим «Простий» або перевірте ці ділянки вручну.", nr))
    ld = [s.region for s in spots if s.anchor is not None]
    if ld:
        out.append(_w("NUM_LEADER", INFO, f"{len(ld)} ділянок мають номер на виносці (номер стоїть поруч, "
                      "лінія з крапкою веде до ділянки).", "Перевірте читабельність виносок у щільних місцях.", ld))
    narrow = [s.region for s in spots if 2 * max(s.radius, 0) / px_per_mm < p.min_width_mm]
    if narrow:
        out.append(_w("AREA_NARROW", WARNING, f"{len(narrow)} ділянок вужчі за {p.min_width_mm} мм.",
                      "Такі ділянки важко розфарбувати пензлем; розгляньте об'єднання із сусідами.", narrow))
    small = [i for i, a in enumerate(region_area_mm2) if a < p.min_area_mm2 * 0.5]
    if small:
        out.append(_w("AREA_SMALL", WARNING, f"{len(small)} ділянок менші за половину мінімальної площі "
                      f"({p.min_area_mm2} мм²).", "Перевірте, чи це важливі деталі (очі, зіниці).", small))
    if colors_final < colors_requested:
        out.append(_w("COLORS_REDUCED", INFO, f"Після об'єднання ділянок залишилось {colors_final} кольорів "
                      f"із заданих {colors_requested}.", "Невикористані кольори не потрапляють у специфікацію."))

    # зони пріоритету (розділ 7.8 ТЗ)
    if not zone_report:
        out.append(_w("PRIORITY_ZONES_NOT_SET", INFO, "Зони пріоритету не позначено: характерні деталі "
                      "(обличчя, очі, силуети) збережуться лише автоматичною картою значущості.",
                      "Для портретів і фото з важливими деталями позначте зони (--zones)."))
    else:
        for z in zone_report["zones"]:
            if z.get("empty"):
                out.append(_w("ZONE_EMPTY", WARNING, f"Зона «{z['name']}» не потрапляє на полотно.",
                              "Перевірте координати зони та систему координат (frame)."))
            elif z["regions_without_number_room"]:
                out.append(_w("ZONE_NUM_NO_ROOM", WARNING, f"У зоні «{z['name']}» {z['regions_without_number_room']} "
                              "дрібних деталей без номера навіть на виносці.",
                              "Перевірте їх вручну, зменште вагу зони (weight) або кількість кольорів."))

    calc = spec["calculation"]
    if calc["provisional"]:
        out.append(_w("SPEC_PROVISIONAL", WARNING, calc["note"],
                      "Виміряйте норму покриття однієї ємності фізичним тестом (розділ 21.5 ТЗ) і задайте її "
                      "через --coverage-mm2 та --coverage-confirmed."))
    many = [pp["number"] for pp in spec["paints"] if pp["containers"] > settings.many_containers_warn]
    if many:
        out.append(_w("SPEC_MANY_CONTAINERS", WARNING, f"Для {len(many)} кольорів потрібно понад "
                      f"{settings.many_containers_warn} ємностей.", "Перевірте специфікацію вручну.", many))
    total = spec["totals"]["canvas_area_mm2"]
    expected = 0.0
    # сума площ кольорів має збігатися з площею полотна (розділ 13.5 ТЗ)
    if "canvas_expected_mm2" in spec["totals"]:
        expected = spec["totals"]["canvas_expected_mm2"]
        if expected and abs(total - expected) / expected > 1e-4:
            out.append(_w("SPEC_AREA_MISMATCH", CRITICAL, "Сума площ кольорів не збігається з площею полотна.",
                          "Помилка геометрії або специфікації: виробничий пакет блокується."))
    return out


def summarize(warnings: list[dict]) -> dict:
    s = {CRITICAL: 0, WARNING: 0, INFO: 0}
    for w in warnings:
        s[w["severity"]] = s.get(w["severity"], 0) + 1
    return s
