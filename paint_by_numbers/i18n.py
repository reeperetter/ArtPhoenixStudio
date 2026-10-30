"""Мова інтерфейсу (українська / англійська).

Вихідні тексти в коді українські; tr(текст) повертає їх як є (uk) або англійський переклад (en). Переклади лежать у
i18n_en.py (ключ --- українське формулювання). Рядки з підстановками (f-рядки) записані шаблонами з {}: tr() зіставляє
готовий рядок із шаблоном і підставляє значення в англійський шаблон, переклавши й самі значення (імена режимів,
статуси тощо). Невідомий рядок повертається без змін, тому інтерфейс ніколи не ламається через відсутній переклад.
Мова задається один раз на запуск (set_language до побудови вікон); зміна в меню вимагає перезапуску."""
from __future__ import annotations

import re

LANGUAGES = {"uk": "Українська", "en": "English"}
LANG = "uk"

_exact: dict[str, str] | None = None
_patterns: list[tuple[re.Pattern, str]] | None = None


def set_language(code: str) -> None:
    global LANG
    LANG = code if code in LANGUAGES else "uk"


def current() -> str:
    return LANG


def _load() -> None:
    global _exact, _patterns
    from .i18n_en import EN
    _exact, pats = {}, []
    for uk, en in EN.items():
        if "{}" in uk:
            parts = uk.split("{}")
            rx = re.compile("^" + "(.*?)".join(re.escape(p) for p in parts) + "$", re.DOTALL)
            pats.append((len("".join(parts)), rx, en))
        else:
            _exact[uk] = en
    pats.sort(key=lambda t: -t[0])                       # спершу найконкретніші шаблони
    _patterns = [(rx, en) for _n, rx, en in pats]


def tr(text):
    """Переклад рядка на поточну мову інтерфейсу (для не-рядків і порожніх значень повертає їх без змін)."""
    if LANG == "uk" or not isinstance(text, str) or not text:
        return text
    if _exact is None:
        _load()
    hit = _exact.get(text)
    if hit is not None:
        return hit
    for rx, en in _patterns:
        m = rx.match(text)
        if m:
            vals = [tr(g) for g in m.groups()]
            out = en
            for v in vals:
                out = out.replace("{}", v, 1)
            return out
    return text
