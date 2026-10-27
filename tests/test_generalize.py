"""Rules added so plans from other offices work (N2): cores without labels, doors on wall
layers, scale without "1:100" text, unit numbers drawn glyph by glyph."""

import fitz
import pytest

from app.extract import Word, read_page
from app.zones import Room, _drawn_doors, _has_step_numbers, _unit_id, detect_zones, scale_from_areas
from harness.samples import GEGMEBI


def test_step_numbers():
    assert _has_step_numbers(["1", "2", "3", "4", "5", "მ"])
    assert _has_step_numbers(["6", "7", "8", "9", "10", "11"])
    assert not _has_step_numbers(["90", "372", "791", "2", "²"])  # dimensions, and "²" isn't a digit


def test_scale_from_written_areas():
    pt2_per_m2 = (72 / 25.4 * 1000 / 100) ** 2  # 1:100
    rooms = {i: Room(i, a * pt2_per_m2 * f, labeled_areas=[a])
             for i, (a, f) in enumerate([(43.9, 1.02), (32.4, 0.97), (113.0, 1.05), (9.3, 0.95)], 1)}
    assert scale_from_areas(rooms) == 100
    assert scale_from_areas({1: rooms[1]}) is None  # too few rooms to trust


def _w(text, x0, size=4.0):
    return Word(text, None, (x0, 100, x0 + 2.5 * len(text), 104), "", "f", size)


def test_unit_id_joins_glyphs():
    name = _w("ოფისი", 10)
    glyphs = [name, _w("-", 23), _w("#", 25.6), _w("0", 28.2), _w("6", 30.8), _w("ქვაბის", 50)]
    assert _unit_id(name, glyphs) == "ოფისი-#06"
    assert _unit_id(_w("ოფისი", 10), [_w("ოფისი", 10), _w("1", 24.5)]) == "ოფისი 1"
    assert _unit_id(_w("ბინა-09", 10), []) == "ბინა-09"


def test_door_arc_on_wall_layer_is_a_door():
    from app.extract import LayerInfo
    from app.layers import classify
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    shape = page.new_shape()
    shape.draw_line((100, 100), (100, 126))                                # leaf, 0.9 m at 1:100
    shape.draw_bezier((100, 126), (114.4, 126), (126, 114.4), (126, 100))  # quarter-circle swing
    shape.finish(color=(0, 0, 0))
    shape.commit()
    data = read_page(doc, 0)
    for d in data.drawings:
        d["layer"] = "Interior - Walls"
    data.layers = {"Interior - Walls": LayerInfo("Interior - Walls", classify("Interior - Walls"))}
    assert len(_drawn_doors(data, pt_per_m=28.35).drawings) == 1
    assert len(_drawn_doors(data, pt_per_m=5.0).drawings) == 0  # same arc is far too big at 1:600


@pytest.mark.skipif(not GEGMEBI.exists(), reason="sample PDFs not mounted")
def test_gegmebi_duplex_stair_stays_in_the_apartment():
    from app.extract import open_pdf
    page = read_page(open_pdf(GEGMEBI), 1)
    zones = detect_zones(page, 1.0)
    cores = [r for r in zones.rooms.values() if r.core]
    assert len(cores) >= 2 and not any(r.unit for r in cores)
    assert "ბინა-02" in zones.units and len(zones.units["ბინა-02"]) >= 5


@pytest.mark.parametrize("label, cls", [
    ("ბინა-01", "residential"), ("bina-01", "residential"), ("Bina 3", "residential"),
    ("ofisi", "business"), ("Office 2", "business"), ("Apartment 4", "residential"),
])
def test_unit_words_in_any_spelling(label, cls):
    from app.acadnusx import fold
    from app.zones import ANCHORS, _ANCHOR_KEYS
    key = next((k for k, f in _ANCHOR_KEYS if fold(label).startswith(f)), None)
    assert key is not None and ANCHORS[key] == cls
    assert next((k for k, f in _ANCHOR_KEYS if fold("binebi").startswith(f)), None) is None  # plural


def test_latin_room_names():
    from app.acadnusx import is_name_word
    assert is_name_word("sadzinebeli") and is_name_word("Office") and is_name_word("საძინებელი")
    assert not any(is_name_word(w) for w in ("W", "D1", "EXIT", "90", "ა-300"))


def test_room_functions():
    from app.functions import function_class, is_accessory
    assert function_class(["პალატა", "18.6", "მ"]) == "institutional"
    assert function_class(["ლაბორატორია"]) == "business"
    assert function_class(["აფთიაქი"]) == "mercantile"
    assert function_class(["საძინებელი", "14.2"]) is None            # apartment rooms have no function
    assert function_class(["კაბინეტი"], strong_only=True) is None     # a study in a flat, an office in a clinic
    assert function_class(["კაბინეტი"]) == "business"
    assert is_accessory(["დამხმარე", "ფართი"]) and is_accessory(["WC"])


def test_fire_and_access_only_on_residential_floors():
    from app.main import MIN_RESIDENTIAL_SHARE_FOR_RULES, RULE_KINDS
    assert RULE_KINDS == {"fire", "accessibility"} and MIN_RESIDENTIAL_SHARE_FOR_RULES >= 0.5


def test_outside_room_classes_match_any_spelling():
    from app.acadnusx import fold
    from app.functions import extra_class
    given = {fold("სტუდენტური კავშირის ოთახი"): "business"}
    assert extra_class(["სტუდენტური", "კავშირის", "ოთახი", "24.5", "მ"], given) == "business"
    assert extra_class(["საძინებელი"], given) is None and extra_class(["x"], None) is None


def test_api_room_classes_must_be_json():
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).post("/sheets", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
                             data={"room_classes": "{not json"})
    assert r.status_code == 422


def test_walls_recognised_by_style_without_layers():
    """No CAD layers: grey wall fills + the pen that runs along them become walls; a pen elsewhere
    (furniture, grid) doesn't."""
    from app.extract import read_page
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    for i in range(60):  # wall segments: grey fill outlined with a 0.6 pen (≥ 50 drawings per pen)
        r = fitz.Rect(50 + (i % 25) * 20, 100 + (i // 25) * 40, 62 + (i % 25) * 20, 106 + (i // 25) * 40)
        page.draw_rect(r, color=None, fill=(0.72, 0.72, 0.72))
        page.draw_line(r.tl, r.tr, color=(0, 0, 0), width=0.6)  # outline as separate strokes,
        page.draw_line(r.bl, r.br, color=(0, 0, 0), width=0.6)  # as CAD exports draw it
    for i in range(60):  # furniture pen, away from the walls
        page.draw_line((50 + i * 8, 300), (54 + i * 8, 340), color=(0, 0, 0), width=0.24)
    data = read_page(doc, 0)
    assert data.has_layers and data.layer_source == "style"
    cats = {n: l.cls.category for n, l in data.layers.items()}
    assert cats["~fill"] == "WALL_FILL" and cats["~wall-0.60"] == "WALL" and cats["~stroke-0.24"] == "UNKNOWN"


def test_no_style_layers_without_wall_fills():
    from app.extract import read_page
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.draw_line((10, 10), (100, 100), color=(0, 0, 0), width=0.6)
    data = read_page(doc, 0)
    assert not data.has_layers and data.layer_source == "pdf"
