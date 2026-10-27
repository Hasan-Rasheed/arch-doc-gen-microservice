"""Occupancy sheets drawn on the original gegmebi sheets, and the API around them."""

import fitz
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.extract import open_pdf, read_page
from app.main import app
from app.sheet import CLASS_STYLE, find_empty_box, hatch_segments, occupancy_sheet, printed_unit_area, title_block
from app.zones import detect_zones
from harness.samples import GEGMEBI

SOURCE = GEGMEBI

needs_pdf = pytest.mark.skipif(not SOURCE.exists(), reason="sample PDFs not mounted")
SCALE = 1.0


def test_hatch_stays_inside_mask():
    mask = np.zeros((100, 100), np.uint8)
    mask[20:60, 30:80] = 255
    segs = hatch_segments(mask, 1.0, spacing_pt=5)
    assert segs
    for (x0, y0), (x1, y1) in segs:
        for x, y in ((x0, y0), (x1, y1)):
            assert 30 <= x < 80 and 20 <= y < 60
        assert abs((x1 - x0) + (y1 - y0)) < 1e-6  # '/' direction: x + y constant


def test_empty_box_prefers_top_right_and_avoids_ink():
    ink = np.zeros((200, 300), np.uint8)
    ink[0:60, 200:300] = 1  # ink in the top-right corner
    x, y = find_empty_box(ink, 1.0, 40, 20, x_max_pt=300, margin_pt=2)
    assert not ink[int(y):int(y) + 20, int(x):int(x) + 40].any()
    assert x + 40 <= 200 or y >= 60
    assert (x + 40 > 150 and y < 10) or (x > 250 and y < 70)  # hugging the corner region


@pytest.fixture(scope="module")
def gegmebi():
    doc = open_pdf(SOURCE)
    return doc, read_page(doc, 0), read_page(doc, 1)


@needs_pdf
def test_title_block(gegmebi):
    _, p0, _ = gegmebi
    lines, number = title_block(p0)
    assert [" ".join(w.display for w in line) for line in lines] == ["-3 სართულის გეგმა", "-10.20 ნიშნულზე"]
    assert number.display == "ა-100"


@needs_pdf
def test_printed_unit_area(gegmebi):
    _, p0, p1 = gegmebi
    assert printed_unit_area(p0, "ბინა-02") == 185.2
    assert printed_unit_area(p1, "ბინა-404") is None


@needs_pdf
def test_occupancy_sheet(gegmebi):
    doc, _, p1 = gegmebi
    zones = detect_zones(p1, SCALE)
    sheet = occupancy_sheet(doc, 1, p1, zones, SCALE, "ka")
    out = sheet.doc[0]
    # Display orientation, same size as the source sheet as seen.
    assert out.rotation == 0 and (round(out.rect.width), round(out.rect.height)) == (round(p1.width), round(p1.height))
    assert sheet.derived_number == "ა-100(ა)"
    assert sheet.title_lines[-1] == "დაკავებულობის გეგმა"
    assert set(sheet.classes) == {"residential", "business"}
    assert {u.name for u in sheet.units} >= {"ბინა-01", "ბინა-02", "ოფისი 1"}

    # The original drawing is still there, and our text was added on top of it.
    text = out.get_text()
    assert "დაკავებულობის გეგმა" in text and "ა-100(ა)" in text and "საქმიანი ჯგუფი (სქ)" in text

    # Purple hatch lands inside the office zone, i.e. overlay and drawing line up.
    pix = out.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).astype(int)
    r, g, b = (np.array(CLASS_STYLE["business"]["rgb"]) * 255).astype(int)
    purple = (abs(img[..., 0] - r) < 40) & (abs(img[..., 1] - g) < 40) & (abs(img[..., 2] - b) < 40)
    zone = zones.masks["business"] > 0
    assert purple[zone].sum() > 0.7 * purple.sum() - 500  # legend swatch is the only purple outside


@needs_pdf
def test_api_skips_pages_without_units():
    client = TestClient(app)
    with SOURCE.open("rb") as f:
        r = client.post("/sheets/occupancy", files={"file": ("gegmebi.pdf", f, "application/pdf")}, data={"lang": "ka"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pageCount"] == 7
    assert [s["index"] for s in body["sheets"]] == [0, 1, 2, 3, 4, 5]
    assert body["skipped"] == [{"index": 6, "reason": "no units found"}]
    assert body["sheets"][0]["derivedNumber"] == "ა-100(ა)"
    assert body["sheets"][0]["image"].startswith("data:image/jpeg;base64,")


@needs_pdf
def test_api_sheets_both_kinds():
    client = TestClient(app)
    with SOURCE.open("rb") as f:
        r = client.post("/sheets", files={"file": ("gegmebi.pdf", f, "application/pdf")},
                        data={"lang": "ka", "kinds": "occupancy,fire"})
    assert r.status_code == 200, r.text
    body = r.json()
    got = [(s["index"], s["kind"], s["derivedNumber"]) for s in body["sheets"]]
    assert got[:2] == [(0, "occupancy", "ა-100(ა)"), (0, "fire", "ა-100(ბ)")]
    assert len(got) == 12


def test_api_rejects_unknown_kind():
    r = TestClient(app).post("/sheets", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
                             data={"kinds": "occupancy,zoning"})
    assert r.status_code == 422


def test_api_rejects_non_pdf():
    r = TestClient(app).post("/sheets/occupancy", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


@needs_pdf
def test_api_plan_matches_the_sheets():
    # /plan answers which kinds each page would get, without drawing: the same pages /sheets draws.
    client = TestClient(app)
    with SOURCE.open("rb") as f:
        plan = client.post("/plan", files={"file": ("gegmebi.pdf", f, "application/pdf")})
    assert plan.status_code == 200, plan.text
    body = plan.json()
    ok = [p for p in body["pages"] if p["verdict"] == "ok"]
    assert body["pageCount"] == 7 and len(ok) == 6
    assert all("occupancy" in p["kinds"] and p["hasLayers"] for p in ok)
    with SOURCE.open("rb") as f:
        sheets = client.post("/sheets", files={"file": ("gegmebi.pdf", f, "application/pdf")}, data={"lang": "ka"}).json()
    drawn = {(s["index"], s["kind"]) for s in sheets["sheets"]}
    planned = {(p["index"], k) for p in ok for k in p["kinds"]}
    # Fire sheets can still be held back after drawing (no unit/corridor walls found).
    assert drawn <= planned and {(i, k) for i, k in planned if k != "fire"} <= drawn


@needs_pdf
def test_unit_outline_is_straighter_and_stays_out_of_other_rooms():
    # 1st floor of gegmebi: the outline follows the walls (door bites closed, fixtures ignored) and
    # never spreads into a corridor or a neighbouring room.
    import cv2
    from app.sheet import outline_polys, unit_outline_polys
    page = read_page(open_pdf(SOURCE.read_bytes()), 3)
    zones = detect_zones(page, 2.0)
    smooth = unit_outline_polys(zones, "residential", 2.0)
    exact = outline_polys(zones.masks["residential"], 2.0)
    assert len(smooth) >= 6
    assert sum(len(p) for p in smooth) < sum(len(p) for p in exact)
    h, w = zones.labels.shape
    for poly in smooth:
        filled = np.zeros((h, w), np.uint8)
        cv2.fillPoly(filled, [np.round(np.array(poly) * 2.0).astype(np.int32)], 1)
        inside = zones.labels[filled > 0]
        unit_rooms = {rid for rids in zones.units.values() for rid in rids}
        foreign = np.isin(inside, list(unit_rooms | {0}), invert=True).mean()
        assert foreign < 0.02, foreign
