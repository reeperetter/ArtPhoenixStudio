"""Чиста (без Qt) логіка зон для інтерфейсу: перетворення рухів миші на опис зони у форматі ТЗ 7.8."""
from __future__ import annotations

MIN_SIZE_PX = 6.0          # менші «кліки» ігноруються (випадковий рух миші)


def _clamp(v: float, hi: float) -> float:
    return min(max(v, 0.0), hi)


def rect_zone(p0, p1, w: float, h: float, name: str, weight: float) -> dict | None:
    x0, x1 = sorted((_clamp(p0[0], w), _clamp(p1[0], w)))
    y0, y1 = sorted((_clamp(p0[1], h), _clamp(p1[1], h)))
    if x1 - x0 < MIN_SIZE_PX or y1 - y0 < MIN_SIZE_PX:
        return None
    return {"name": name, "shape": "rect", "weight": weight,
            "x0": x0 / w, "y0": y0 / h, "x1": x1 / w, "y1": y1 / h}


def ellipse_zone(p0, p1, w: float, h: float, name: str, weight: float) -> dict | None:
    """Еліпс, вписаний у прямокутник, який протягнув оператор."""
    r = rect_zone(p0, p1, w, h, name, weight)
    if r is None:
        return None
    return {"name": name, "shape": "ellipse", "weight": weight,
            "cx": (r["x0"] + r["x1"]) / 2, "cy": (r["y0"] + r["y1"]) / 2,
            "rx": (r["x1"] - r["x0"]) / 2, "ry": (r["y1"] - r["y0"]) / 2}


def polygon_zone(points, w: float, h: float, name: str, weight: float) -> dict | None:
    pts = [(_clamp(x, w) / w, _clamp(y, h) / h) for x, y in points]
    if len(pts) < 3:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if (max(xs) - min(xs)) * w < MIN_SIZE_PX or (max(ys) - min(ys)) * h < MIN_SIZE_PX:
        return None
    return {"name": name, "shape": "polygon", "weight": weight, "points": [list(p) for p in pts]}


def zone_outline(z: dict, w: float, h: float, n: int = 72) -> list[tuple[float, float]]:
    """Контур зони в пікселях відображуваного зображення (для малювання)."""
    import math
    s = z["shape"]
    if s == "rect":
        return [(z["x0"] * w, z["y0"] * h), (z["x1"] * w, z["y0"] * h), (z["x1"] * w, z["y1"] * h),
                (z["x0"] * w, z["y1"] * h)]
    if s == "polygon":
        return [(x * w, y * h) for x, y in z["points"]]
    a = math.radians(z.get("angle", 0.0))
    out = []
    for i in range(n):
        t = 2 * math.pi * i / n
        ex, ey = z["rx"] * w * math.cos(t), z["ry"] * h * math.sin(t)
        out.append((z["cx"] * w + ex * math.cos(a) - ey * math.sin(a),
                    z["cy"] * h + ex * math.sin(a) + ey * math.cos(a)))
    return out


def point_in_zone(z: dict, x: float, y: float, w: float, h: float) -> bool:
    poly = zone_outline(z, w, h)
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def zone_area(z: dict) -> float:
    """Нормована площа (для вибору найменшої зони під курсором)."""
    poly = zone_outline(z, 1.0, 1.0)
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2.0
