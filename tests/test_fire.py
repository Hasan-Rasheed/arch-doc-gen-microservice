"""Fire-rated walls vs the architects' fire sheets (gegmebi → album p.39-44), and the fire sheet."""
from pathlib import Path

import pytest

from app.extract import open_pdf, read_page
from app.fire import CORRIDOR, STAIR, UNIT, _open_air, _rating, fire_lines, separation_508
from app.sheet import fire_sheet
from app.zones import Room, detect_zones
from harness.answer_key import match_source_page, to_source_coords
from harness.fire_key import fire_truth, line_score

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "Documents Generated" / "DownloadServlet (1).pdf"
SOURCE = ROOT / "Sample Input Diagrams & Description input" / "gegmebi (2).pdf"
needs_pdfs = pytest.mark.skipif(not (TARGET.exists() and SOURCE.exists()), reason="sample PDFs not mounted")

SCALE = 2.0
# Scores at the time of writing (scale 2.0), 2h P/R · 1h P/R:
#   p40 0.78/0.87 · 0.61/0.78   p41 0.74/0.85 · 0.86/0.93   p43 0.52/0.82 · 0.87/0.92
#   p42 0.48/0.84 · 0.82/0.92 (ground floor: the open walkway is found as a corridor, A9)
# The album doesn't mark every exterior wall, which caps 2-hour precision. p44 not gated yet.
FLOORS = {40: (0.45, 0.75, 0.55, 0.7), 41: (0.45, 0.75, 0.55, 0.7), 42: (0.4, 0.75, 0.7, 0.8),
          43: (0.45, 0.75, 0.55, 0.7)}


def test_ratings():
    # Cores: №41 §713.4 / §1022.2 — 2 h from four connected storeys, 1 h below that.
    assert _rating(UNIT, STAIR) == "2h" and _rating(CORRIDOR, STAIR) == "2h"
    assert _rating(UNIT, STAIR, storeys=6) == "2h" and _rating(UNIT, STAIR, storeys=3) == "1h"
    # Dwellings: §420.2 fire partitions (§708.3 ≥ 1 h), also toward other uses.
    assert _rating(UNIT, UNIT, "residential", "residential") == "1h"
    assert _rating(UNIT, UNIT, "residential", "business") == "1h"
    assert _rating(UNIT, UNIT, "business", "business") is None
    # Corridors: Table 1018.1 without sprinklers.
    assert _rating(UNIT, CORRIDOR) == "1h" and _rating(CORRIDOR, UNIT) == "1h"
    assert _rating(CORRIDOR, CORRIDOR) is None
    # Sprinklered (the project says so): residential corridors 0.5 h, others none.
    assert _rating(UNIT, CORRIDOR, "residential", sprinklered=True) == "0.5h"
    assert _rating(CORRIDOR, UNIT, None, "business", sprinklered=True) is None
    assert _rating(UNIT, STAIR, sprinklered=True) == "2h"
    assert _rating(UNIT, UNIT, "residential", "business", sprinklered=True) == "1h"


def test_table_508_4_between_non_residential_groups():
    # Values read from the clean №41 text (p. 176) — the same as IBC 2012 Table 508.4.
    assert _rating(UNIT, UNIT, "parking", "business") == "2h"
    assert _rating(UNIT, UNIT, "parking", "business", sprinklered=True) == "1h"
    assert _rating(UNIT, UNIT, "assembly", "parking") == "1h"
    assert _rating(UNIT, UNIT, "assembly", "parking", sprinklered=True) is None
    assert _rating(UNIT, UNIT, "business", "mercantile") is None
    assert separation_508("institutional", "residential") == "2h"  # NP: may not adjoin
    assert separation_508("institutional", "residential", sprinklered=True) == "1h"


def test_open_air_only_when_nothing_else_is_named():
    assert _open_air(Room(1, 100, words=["აივანი", "8.59", "მ", "2"]))
    assert not _open_air(Room(2, 100, words=["აივანი", "ბინა-06", "საერთო", "ოთახი,", "სამზარეულო"]))


@pytest.fixture(scope="module")
def docs():
    tdoc, sdoc = open_pdf(TARGET), open_pdf(SOURCE)
    return tdoc, sdoc, [read_page(sdoc, i) for i in range(len(sdoc))]


@needs_pdfs
@pytest.mark.parametrize("target_page", sorted(FLOORS))
def test_fire_lines_match_architects(docs, target_page):
    tdoc, _, sources = docs
    truth = fire_truth(tdoc, target_page - 1, SCALE)
    match = match_source_page(read_page(tdoc, target_page - 1), sources)
    tmasks = {c: to_source_coords(m, match.offset, SCALE) for c, m in truth.masks.items()}
    page = sources[match.index]
    s = line_score(fire_lines(page, detect_zones(page, SCALE), SCALE).masks, tmasks, SCALE)
    p2, r2, p1, r1 = FLOORS[target_page]
    assert s["2h"]["precision"] >= p2 and s["2h"]["recall"] >= r2, s
    assert s["1h"]["precision"] >= p1 and s["1h"]["recall"] >= r1, s


@needs_pdfs
def test_fire_sheet(docs):
    _, sdoc, sources = docs
    page = sources[1]
    sheet = fire_sheet(sdoc, 1, page, detect_zones(page, 1.0), 1.0, "ka")
    assert sheet.derived_number == "ა-100(ბ)"
    assert sheet.title_lines[-1] == "ხანძარსაწინააღმდეგო გეგმა"
    assert sheet.classes == ["2h", "1h"]
    text = sheet.doc[0].get_text()
    assert "2 სთ-იანი ხანძარმედეგობა" in text and "1 სთ-იანი ხანძარმედეგობა" in text


@needs_pdfs
@pytest.mark.parametrize("target_page, min_p, min_r, n_paths", [(29, 0.3, 0.45, 2), (32, 0.8, 0.6, 1)])
def test_escape_routes_match_architects(docs, target_page, min_p, min_r, n_paths):
    """Green longest-travel-distance lines (album occupancy sheets). Scores at the time of writing:
    p29 0.36/0.51, p30 0.30/0.36, p31 0.35/0.50, p32 0.95/0.71 — on −1…2 the architects route the
    farthest flat to the north stair, we to the nearest (what №41 limits)."""
    from app.egress import egress_mask, egress_paths
    from harness.answer_key import occupancy_truth
    tdoc, _, sources = docs
    truth = occupancy_truth(tdoc, target_page - 1, SCALE)
    match = match_source_page(read_page(tdoc, target_page - 1), sources)
    page = sources[match.index]
    zones = detect_zones(page, SCALE)
    paths = egress_paths(page, zones, SCALE)
    assert len(paths) == n_paths
    s = line_score({"e": egress_mask(paths, zones.labels.shape, SCALE)},
                   {"e": to_source_coords(truth.egress, match.offset, SCALE)}, SCALE, tol_pt=8)["e"]
    assert s["precision"] >= min_p and s["recall"] >= min_r, s


@needs_pdfs
def test_no_escape_route_when_a_stair_was_cut_off(docs):
    """gegmebi −2: the south stair's door isn't read, so the only route found is a 52 m detour to
    the north stair — that false travel distance must not be drawn."""
    from app.egress import egress_paths
    _, _, sources = docs
    page = sources[1]
    assert egress_paths(page, detect_zones(page, SCALE), SCALE) == []
