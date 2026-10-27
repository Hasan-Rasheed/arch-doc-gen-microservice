"""Regression floor for occupancy zones vs the architects' answer key (gegmebi → album p.27-32)."""

import pytest

from app.extract import open_pdf, read_page
from app.zones import detect_zones
from harness.answer_key import match_source_page, occupancy_truth, to_source_coords
from harness.score import score
from harness.samples import GEGMEBI, GEGMEBI_ALBUM

TARGET = GEGMEBI_ALBUM
SOURCE = GEGMEBI

pytestmark = pytest.mark.skipif(not (TARGET.exists() and SOURCE.exists()), reason="sample PDFs not mounted")

SCALE = 1.0
# Scores at the time of writing (scale 2.0): 0.95 0.88 0.89 0.85 0.87 0.90, spill ≤ 0.033.
# Tests run at SCALE 1.0 for speed, which costs a few points (p.31: 0.79 vs 0.87 at 2.0).
MIN_IOU, MAX_SPILL = 0.75, 0.06


@pytest.fixture(scope="module")
def docs():
    tdoc, sdoc = open_pdf(TARGET), open_pdf(SOURCE)
    return tdoc, sdoc, [read_page(sdoc, i) for i in range(len(sdoc))]


@pytest.mark.parametrize("target_page", [27, 28, 29, 30, 31, 32])
def test_zones_match_architects(docs, target_page):
    tdoc, sdoc, sources = docs
    truth = occupancy_truth(tdoc, target_page - 1, SCALE)
    match = match_source_page(read_page(tdoc, target_page - 1), sources)
    truth_masks = {c: to_source_coords(m, match.offset, SCALE) for c, m in truth.masks.items()}
    zones = detect_zones(sources[match.index], SCALE)
    s = score(zones.masks, truth_masks)
    assert s["meanIoU"] >= MIN_IOU, s
    assert s["spill"] <= MAX_SPILL, s


def test_unit_anchor_names(docs):
    _, _, sources = docs
    zones = detect_zones(sources[3], SCALE)
    assert "ბინა-09" in zones.units and not any(a.startswith("ბინა-09 ") for a in zones.units)
    office = detect_zones(sources[1], SCALE)
    assert office.unit_class.get("ოფისი 1") == "business"
