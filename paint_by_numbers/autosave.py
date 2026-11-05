"""Автозбереження ручних правок (відновлення після збою). Знімок --- мінімальний «проєкт» у службовій папці:
розбиття + налаштування, а фото клієнта НЕ копіюється (лише абсолютний шлях до оригіналу)."""
from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .applog import log_dir
from .settings import ALGORITHM_VERSION, PROJECT_FORMAT_VERSION

_lock = threading.Lock()


def recovery_dir() -> Path:
    return log_dir() / "recovery"


def has_recovery(root: Path | None = None) -> bool:
    return ((root or recovery_dir()) / "project" / "project.json").is_file()


def clear(root: Path | None = None) -> None:
    with _lock:
        shutil.rmtree(root or recovery_dir(), ignore_errors=True)


def snapshot(res, photo: str | Path, original_name: str | None = None, root: Path | None = None) -> Path:
    """Атомарно записує знімок (мінімум полів, потрібних open_project)."""
    root = root or recovery_dir()
    s = res.settings
    photo = Path(photo).resolve()
    tmp = root.with_name(root.name + ".tmp")
    with _lock:
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "project").mkdir(parents=True)
        np.savez_compressed(tmp / "project/regions.npz", labels=res.rm.labels.astype(np.int32),
                            region_color=res.rm.color.astype(np.int32), palette_lab=res.rm.palette_lab,
                            palette_lab_raw=(res.palette_lab_raw if res.palette_lab_raw is not None
                                             else res.rm.palette_lab),
                            n_before=np.int64(res.rm.n_before))
        (tmp / "project/project.json").write_text(json.dumps({
            "project_format_version": PROJECT_FORMAT_VERSION,
            "algorithm_version": ALGORITHM_VERSION,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "order_number": s.order_number, "project_name": s.project_name, "status": "autosave",
            "settings": s.to_dict(),
            "effective": {"merged_for_numbers": res.report.get("regions_merged_for_numbers", 0)},
            "source": {"file": str(photo), "original_name": original_name or photo.name},
            "regions_file": "project/regions.npz",
        }, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(root, ignore_errors=True)
        tmp.rename(root)
    return root


def snapshot_async(res, photo, original_name=None, root: Path | None = None) -> threading.Thread:
    """Запис у фоні; помилки не повинні заважати роботі (лише в журнал)."""
    def work():
        try:
            snapshot(res, photo, original_name, root)
        except Exception as e:                      # noqa: BLE001
            from .applog import log_exception
            log_exception(e, "автозбереження")
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t
