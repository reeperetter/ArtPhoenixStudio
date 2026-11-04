"""Оцінка придатності фото до обробки (розділи 5.3--5.4 ТЗ). Лише класичні методи: градієнти, гістограми, оцінка шуму.

Усі пороги --- стартові гіпотези, які треба уточнити на контрольному наборі фото (розділ 21.1 ТЗ); жодне попередження
не блокує роботу: рішення про прийняття замовлення лишається за оператором (розділ 5.4 ТЗ)."""
from __future__ import annotations

import cv2
import numpy as np

NORM_SIDE = 1000          # довша сторона копії, на якій рахуються показники (щоб пороги не залежали від розміру фото)

# пороги (гіпотези)
BLUR_VERY = 4.2           # відносна різкість (_sharpness): нижче --- сильне розмиття
BLUR_SOFT = 6.0
NOISE_SIGMA_WARN = 5.0    # σ шуму в одиницях яскравості 0..255 на копії NORM_SIDE
NOISE_SIGMA_STRONG = 9.0
DARK_MEDIAN_L = 28.0      # медіана L* (0..100)
BRIGHT_MEDIAN_L = 82.0
CLIP_DARK_SHARE = 0.55    # частка майже чорних пікселів
CLIP_BRIGHT_SHARE = 0.25  # частка майже білих пікселів
LOW_CONTRAST_RANGE = 38.0 # p95 - p5 по L*
EST_REGIONS_FACTOR = 0.28 # калібровано на 5 фото в режимі «Збалансований» (груба оцінка: реальні значення в межах ~2 разів)
DETAIL_RISK_MEDIUM, DETAIL_RISK_HIGH = 50.0, 90.0


def _norm_gray(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    s = NORM_SIDE / max(h, w)
    if s < 1.0:
        bgr = cv2.resize(bgr, (max(int(w * s), 8), max(int(h * s), 8)), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _noise_sigma(g: np.ndarray) -> float:
    """Оцінка σ шуму за Іммеркером (швидка згортка, нечутлива до плавних структур)."""
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    r = np.abs(cv2.filter2D(g.astype(np.float32), -1, k, borderType=cv2.BORDER_REFLECT))[1:-1, 1:-1]
    return float(np.sqrt(np.pi / 2.0) * r.mean() / 6.0)


def _sharpness(g: np.ndarray, sigma_noise: float) -> float:
    """Ефективна різкість: 95-й перцентиль модуля градієнта Собеля на згладженій копії мінус внесок шуму.
    Не залежить від кількості текстури так сильно, як дисперсія Лапласіана; для розмитого фото падає."""
    sm = cv2.GaussianBlur(g.astype(np.float32), (0, 0), 1.0)
    gx, gy = cv2.Sobel(sm, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(sm, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    # відносна різкість: найкрутіший край (99-й перцентиль градієнта) відносно загального діапазону яскравості кадру,
    # тож темне чи низькоконтрастне фото саме по собі не вважається розмитим
    rng = float(np.percentile(g, 95) - np.percentile(g, 5))
    return float(np.percentile(mag, 99.0) / max(rng, 20.0) * 10.0)


def assess_photo(bgr: np.ndarray, canvas_mm: tuple[float, float] | None = None, min_width_mm: float = 2.0,
                 min_area_mm2: float = 12.0) -> tuple[dict, list[dict]]:
    """Повертає (показники, попередження). bgr --- робоча копія фото (uint8)."""
    g = _norm_gray(bgr)
    lab = cv2.cvtColor(cv2.resize(bgr, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0,
                       cv2.COLOR_BGR2Lab)
    L = lab[..., 0]
    sigma = _noise_sigma(g)
    sharp = _sharpness(g, sigma)
    med = float(np.median(L))
    p5, p95 = (float(v) for v in np.percentile(L, [5, 95]))
    dark_share = float((g < 16).mean())
    bright_share = float((g > 245).mean())
    # деталі: частка пікселів із сильним краєм; складність сцени: краї + різноманіття кольорів
    sm = cv2.GaussianBlur(g, (0, 0), 1.2)
    edges = cv2.Canny(sm, 40, 110)
    edge_density = float((edges > 0).mean())
    q = (lab[..., 1:] / 8.0).astype(np.int32)
    hist = np.bincount(((q[..., 0] + 16) * 40 + (q[..., 1] + 16)).ravel().clip(0, 4095), minlength=4096).astype(np.float64)
    pr = hist[hist > 0] / hist.sum()
    chroma_entropy = float(-(pr * np.log2(pr)).sum())
    complexity = float(np.clip(edge_density / 0.12, 0.0, 1.0) * 0.7 + np.clip(chroma_entropy / 7.0, 0.0, 1.0) * 0.3)
    metrics = {
        "sharpness": round(sharp, 2), "noise_sigma": round(sigma, 2), "median_L": round(med, 1),
        "contrast_range_L": round(p95 - p5, 1), "dark_share": round(dark_share, 3), "bright_share": round(bright_share, 3),
        "edge_density": round(edge_density, 4), "scene_complexity": round(complexity, 2),
    }
    if canvas_mm:
        # орієнтовна кількість ділянок на 100 см²: довжина країв / (4 x мін. ширина), на норму 0.5 ділянки на мм² краю
        area_cm2 = canvas_mm[0] * canvas_mm[1] / 100.0
        scale = max(canvas_mm) / max(g.shape)                           # мм на піксель копії
        edge_len_mm = float((edges > 0).sum()) * scale
        est_regions = edge_len_mm / max(4.0 * min_width_mm, 1e-3) * EST_REGIONS_FACTOR
        metrics["est_regions_per_100cm2"] = round(est_regions / max(area_cm2, 1e-3) * 100.0, 1)
    diff = "low" if complexity < 0.35 else "medium" if complexity < 0.6 else "high"
    metrics["painting_difficulty"] = diff
    risk = "low"
    if canvas_mm and metrics["est_regions_per_100cm2"] > DETAIL_RISK_HIGH:
        risk = "high"
    elif canvas_mm and metrics["est_regions_per_100cm2"] > DETAIL_RISK_MEDIUM:
        risk = "medium"
    metrics["detail_loss_risk"] = risk

    w: list[dict] = []

    def add(code, sev, msg, rec):
        w.append({"code": code, "severity": sev, "message": msg, "recommendation": rec})

    if sharp < BLUR_VERY:
        add("IMG_BLUR", "warning", "Фото сильно розмите: дрібні деталі (очі, вії, текстури) не відновляться.",
            "Попросіть у замовника різкіше фото, інакше обличчя й дрібні деталі вийдуть спрощеними.")
    elif sharp < BLUR_SOFT:
        add("IMG_BLUR", "info", "Фото трохи нечітке: найдрібніші деталі можуть втратитися.",
            "Для портрета краще різкіше фото; перевірте очі й губи в результаті.")
    if sigma > NOISE_SIGMA_STRONG:
        add("IMG_NOISY", "warning", "Фото має сильний шум: контури стануть рваними.",
            "Візьміть фото з кращим освітленням; зменшіть деталізацію або позначте зони пріоритету.")
    elif sigma > NOISE_SIGMA_WARN:
        add("IMG_NOISY", "info", "Фото має помітний шум: програма його згладжує, але дрібні деталі можуть постраждати.",
            "Перевірте результат у зонах із дрібними деталями.")
    if med < DARK_MEDIAN_L or dark_share > CLIP_DARK_SHARE:
        add("IMG_DARK", "warning", "Фото занадто темне: у тінях багато деталей зіллються в чорне.",
            "Попросіть світліше фото. Нічого автоматично не підсвічується, щоб не спотворити кольори.")
    if med > BRIGHT_MEDIAN_L or bright_share > CLIP_BRIGHT_SHARE:
        add("IMG_BRIGHT", "warning", "Фото пересвічене: світлі ділянки зіллються в білий.",
            "Попросіть фото з меншою експозицією або перевірте світлі області в результаті.")
    if p95 - p5 < LOW_CONTRAST_RANGE:
        add("IMG_LOW_CONTRAST", "info", "Контраст фото низький: картина вийде «пласкою», а межі між кольорами слабкими.",
            "Збільште кількість кольорів або деталізацію й позначте зони пріоритету.")
    if risk == "high":
        add("IMG_DETAIL_LOSS", "info", "Багато дрібних деталей для цього розміру полотна: частину доведеться спростити.",
            "Збільште полотно, оберіть режим докладніший або позначте зони пріоритету на найважливіших деталях.")
    if diff == "high":
        add("IMG_COMPLEX", "info", "Складна сцена: розфарбовування буде трудомістким.",
            "Попередьте замовника або оберіть простіший режим.")
    return metrics, w
