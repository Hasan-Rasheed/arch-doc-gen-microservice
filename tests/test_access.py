"""Accessible routes vs the architects' accessibility sheets (gegmebi → album p.33-38)."""
from pathlib import Path

import pytest

from app.access import accessible_routes
from app.extract import open_pdf, read_page
from app.sheet import access_sheet
from app.zones import detect_zones
from harness.answer_key import match_source_page, to_source_coords
from harness.fire_key import access_truth, area_score

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "Documents Generated" / "DownloadServlet (1).pdf"
SOURCE = ROOT / "Sample Input Diagrams & Description input" / "gegmebi (2).pdf"
pytestmark = pytest.mark.skipif(not (TARGET.exists() and SOURCE.exists()), reason="sample PDFs not mounted")

SCALE = 2.0
# Scores at the time of writing (scale 2.0), precision / recall — routes now cross each room to
# its far side (A11), trading a little precision for recall (F1 up on every floor):
#   p34 0.63/0.56   p35 0.67/0.72   p36 0.69/0.74   p37 0.68/0.74   p38 0.79/0.64
FLOORS = {34: (0.55, 0.5), 35: (0.6, 0.65), 36: (0.6, 0.65), 37: (0.6, 0.65), 38: (0.7, 0.55)}


@pytest.fixture(scope="module")
def docs():
    tdoc, sdoc = open_pdf(TARGET), open_pdf(SOURCE)
    return tdoc, sdoc, [read_page(sdoc, i) for i in range(len(sdoc))]


@pytest.mark.parametrize("target_page", sorted(FLOORS))
def test_routes_match_architects(docs, target_page):
    tdoc, _, sources = docs
    match = match_source_page(read_page(tdoc, target_page - 1), sources)
    truth = to_source_coords(access_truth(tdoc, target_page - 1, SCALE), match.offset, SCALE)
    page = sources[match.index]
    s = area_score(accessible_routes(page, detect_zones(page, SCALE), SCALE).route, truth, SCALE)
    min_p, min_r = FLOORS[target_page]
    assert s["precision"] >= min_p and s["recall"] >= min_r, s


def test_no_route_where_the_album_has_none(docs):
    _, _, sources = docs
    page = sources[0]  # floor −3: one duplex apartment below the stairs, no route in the album
    assert not accessible_routes(page, detect_zones(page, SCALE), SCALE).route.any()


def test_access_sheet(docs):
    _, sdoc, sources = docs
    page = sources[2]
    sheet = access_sheet(sdoc, 2, page, detect_zones(page, 1.0), 1.0, "ka")
    assert sheet.derived_number == "ა-101(გ)"
    assert sheet.title_lines[-1] == "მისაწვდომობის გეგმა"
    assert sheet.classes == ["route", "clearance", "circle"]
    assert "მისაწვდომი მარშრუტი" in sheet.doc[0].get_text()


@pytest.mark.parametrize("target_page, min_p, min_r", [(35, 0.7, 0.4), (36, 0.7, 0.4), (37, 0.7, 0.4)])
def test_door_clearances_match_architects(docs, target_page, min_p, min_r):
    """Teal manoeuvring boxes at route doors. At the time of writing: p34 0.77/0.39,
    p35 0.80/0.50, p36 0.82/0.51, p37 0.82/0.51, p38 0.77/0.29."""
    import cv2
    import numpy as np
    from app.access import door_clearances
    from app.extract import rasterize
    from harness.answer_key import _close, _color_of, _layer_subset, building_extent
    from harness.fire_key import line_score
    tdoc, _, sources = docs
    tpage = read_page(tdoc, target_page - 1)
    match = match_source_page(tpage, sources)
    sub = _layer_subset(tpage, lambda d: "MISACV" in (d.get("layer") or "") and _close(_color_of(d), (0.32, 0.57, 0.65)))
    truth = to_source_coords(cv2.bitwise_and(rasterize(sub, SCALE, min_px=2), building_extent(tpage, SCALE)), match.offset, SCALE)
    page = sources[match.index]
    zones = detect_zones(page, SCALE)
    pred = np.zeros(zones.labels.shape, np.uint8)
    for b in door_clearances(page, zones, SCALE):
        cv2.polylines(pred, [np.round(np.array(b) * SCALE).astype(np.int32)], True, 255, 2)
    s = line_score({"b": pred}, {"b": truth}, SCALE, tol_pt=6)["b"]
    assert s["precision"] >= min_p and s["recall"] >= min_r, s
