import json

import pytest

from paint_by_numbers.export.assembly import DEFAULT_KIT_ITEMS, load_kit_items, write_assembly_pdf


def _spec(n=3, cont=2, prov=True):
    paints = [{"number": i + 1, "paint_code": f"S-{i + 1:02d}", "paint_name": f"Фарба {i + 1}", "hex": "#aa5544",
               "containers": cont + i, "total_ml": 3.0 * (cont + i)} for i in range(n)]
    return {"paints": paints, "totals": {"paints": n, "containers": sum(p["containers"] for p in paints),
                                         "total_ml": sum(p["total_ml"] for p in paints)},
            "calculation": {"provisional": prov}}


META = {"order_number": "42", "project_name": "Тест", "width_mm": 300, "height_mm": 400}


def test_pdf_written_and_many_pages(tmp_path):
    p = tmp_path / "a.pdf"
    info = write_assembly_pdf(p, _spec(), META)
    assert p.read_bytes()[:4] == b"%PDF" and info["cyrillic_font"] and info["items"] == len(DEFAULT_KIT_ITEMS)
    big = tmp_path / "b.pdf"
    write_assembly_pdf(big, _spec(n=24, cont=5), META, [{"name": "Пензлик", "qty": 2}])
    assert big.stat().st_size > p.stat().st_size


def test_kit_items_loading(tmp_path):
    f = tmp_path / "k.json"
    f.write_text(json.dumps([{"name": "Пензлик №2", "qty": 2}]), encoding="utf-8")
    assert load_kit_items(f) == [{"name": "Пензлик №2", "qty": 2}]
    f.write_text(json.dumps({"items": [{"name": "Рамка"}]}), encoding="utf-8")
    assert load_kit_items(f) == [{"name": "Рамка", "qty": 1}]
    for bad in ([], [{"qty": 1}], [{"name": "x", "qty": 0}], [{"name": "x", "qty": "2"}]):
        f.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            load_kit_items(f)
    assert load_kit_items(None) == DEFAULT_KIT_ITEMS and load_kit_items(None) is not DEFAULT_KIT_ITEMS


def test_package_contains_assembly_sheet(tmp_path):
    import cv2, numpy as np
    from paint_by_numbers.generate import generate
    from paint_by_numbers.settings import Settings
    img = np.full((120, 160, 3), (180, 160, 140), np.uint8)
    cv2.circle(img, (80, 60), 30, (50, 70, 190), -1)
    cv2.imwrite(str(tmp_path / "t.png"), img)
    res = generate(str(tmp_path / "t.png"), Settings(width_mm=80.0, n_colors=5, order_number="as",
                                                    extra={"kit_items": [{"name": "Рамка", "qty": 1}]}), tmp_path / "o")
    assert (res.out_dir / "production" / "assembly_sheet.pdf").stat().st_size > 1000
