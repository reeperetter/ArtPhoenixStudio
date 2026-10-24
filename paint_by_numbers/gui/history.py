"""Історія змін для «Відмінити/Повторити»: знімки стану (без Qt, тож перевіряється окремо)."""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

MERGE_WINDOW_S = 1.0       # послідовні правки одного й того самого поля впродовж цього часу --- один крок
DEFAULT_LIMIT = 100


@dataclass
class _Entry:
    state: Any
    label: str
    key: Any = None
    t: float = 0.0


@dataclass
class UndoStack:
    """Лінійна історія знімків. Перший запис --- початковий стан (від нього відмінити вже нічого)."""
    initial: Any
    limit: int = DEFAULT_LIMIT
    _items: list[_Entry] = field(default_factory=list)
    _pos: int = 0

    def __post_init__(self):
        self.reset(self.initial)

    def reset(self, state) -> None:
        self._items = [_Entry(copy.deepcopy(state), "початковий стан")]
        self._pos = 0

    @property
    def position(self) -> int:
        """Скільки кроків від початкового стану (для історії правок ділянок: кількість діючих правок)."""
        return self._pos

    @property
    def can_undo(self) -> bool:
        return self._pos > 0

    @property
    def can_redo(self) -> bool:
        return self._pos < len(self._items) - 1

    @property
    def undo_label(self) -> str:
        return self._items[self._pos].label if self.can_undo else ""

    @property
    def redo_label(self) -> str:
        return self._items[self._pos + 1].label if self.can_redo else ""

    def push(self, state, label: str, key=None, now: float | None = None) -> None:
        """Записує новий стан. Якщо ключ збігається з попереднім записом і пройшло менше MERGE_WINDOW_S,
        запис оновлюється замість додавання (наприклад, поки утримують стрілку лічильника)."""
        now = time.monotonic() if now is None else now
        top = self._items[self._pos]
        if key is not None and self._pos > 0 and top.key == key and now - top.t <= MERGE_WINDOW_S \
                and self._pos == len(self._items) - 1:
            top.state, top.t = copy.deepcopy(state), now
            return
        del self._items[self._pos + 1:]                       # нова дія скасовує «повторити»
        self._items.append(_Entry(copy.deepcopy(state), label, key, now))
        if len(self._items) > self.limit + 1:
            del self._items[0]
        self._pos = len(self._items) - 1

    def undo(self):
        """Повертає попередній стан або None."""
        if not self.can_undo:
            return None
        self._pos -= 1
        return copy.deepcopy(self._items[self._pos].state)

    def redo(self):
        if not self.can_redo:
            return None
        self._pos += 1
        return copy.deepcopy(self._items[self._pos].state)
