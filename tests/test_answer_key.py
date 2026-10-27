
import pytest

from app.extract import open_pdf, read_page
from harness.answer_key import match_source_page, occupancy_truth, to_source_coords
from harness.build import rectangles_of
from harness.score import score
from harness.samples import GEGMEBI, GEGMEBI_ALBUM

TARGET = GEGMEBI_ALBUM
SOURCE = GEGMEBI

pytestmark = pytest.mark.skipif(not (TARGET.exists() and SOURCE.exists()), reason="sample PDFs not mounted")

SCALE = 1.0


@pytest.fixture(scope="module")
def docs():
    tdoc, sdoc = open_pdf(TARGET), open_pdf(SOURCE)
    return tdoc, [read_page(sdoc, i) for i in range(len(sdoc))]


# Target occupancy sheet (1-based) -> input page it was drawn over, from the title blocks.
EXPECTED = {27: 1, 28: 2, 29: 3, 30: 4, 31: 5, 32: 6}


@pytest.mark.parametrize("target_page, source_page", EXPECTED.items())
def test_occupancy_sheet_matches_source(docs, target_page, source_page):
    tdoc, sources = docs
    truth = occupancy_truth(tdoc, target_page - 1, SCALE)
    assert truth is not None and "დაკავებულობის" in truth.title
    assert (truth.masks["residential"] > 0).any()
    match = match_source_page(read_page(tdoc, target_page - 1), sources)
    assert match.index + 1 == source_page
    assert match.iou > 0.8


def test_shifted_sheet_offset(docs):
    """p.28 was plotted with the view moved; the match must find the shift, not a wrong page."""
    tdoc, sources = docs
    match = match_source_page(read_page(tdoc, 27), sources)
    dx, dy = match.offset
    assert abs(dx - 17.8) < 2 and abs(dy - 10.9) < 2


def test_non_occupancy_sheets_have_no_truth(docs):
    tdoc, _ = docs
    for page in (20, 34, 40):  # raw plan, accessibility, fire (fire has legend swatches only)
        truth = occupancy_truth(tdoc, page - 1, SCALE)
        assert truth is None or not any((m > 0).any() for m in truth.masks.values())


def test_scoring_reference_points(docs):
    tdoc, sources = docs
    truth = occupancy_truth(tdoc, 27, SCALE)
    match = match_source_page(read_page(tdoc, 27), sources)
    masks = {c: to_source_coords(m, match.offset, SCALE) for c, m in truth.masks.items()}
    assert score(masks, masks)["meanIoU"] == 1.0
    rects = score({c: rectangles_of(m) for c, m in masks.items()}, masks)
    # Even perfectly placed rectangles spill well outside the architects' zones.
    assert rects["meanIoU"] < 0.8 and rects["spill"] > 0.2
