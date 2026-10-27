
import cv2
import numpy as np
import pytest

from app.extract import boundary_mask, open_pdf, read_page, render
from harness.samples import GEGMEBI


pytestmark = pytest.mark.skipif(not GEGMEBI.exists(), reason="sample PDFs not mounted")


@pytest.fixture(scope="module")
def page2():
    doc = open_pdf(GEGMEBI)
    return doc, read_page(doc, 1)  # floor -2 (office + apartments)


def test_display_space_and_layers(page2):
    _, page = page2
    assert page.rotation == 270
    assert (page.width, page.height) == (1191, 842)  # landscape, as displayed
    assert page.has_layers
    assert page.layers["COLUMN    (NEO-A)"].cls.category == "COLUMN"
    assert page.layers["COLUMN    (NEO-A)"].paths > 0


def test_room_labels_decoded_and_positioned(page2):
    _, page = page2
    by_text = {w.text: w for w in page.words}
    w = by_text["bina-01"]
    assert w.georgian == "ბინა-01"
    # pdftotext (display space) puts bina-01 at x 426-440, y 574-577
    x0, y0, x1, y1 = w.bbox
    assert 424 < x0 < 428 and 572 < y0 < 578 and 438 < x1 < 442
    # Room labels are not reliably on a "text" layer: bina-01 sits on a dimension-text layer.
    assert w.layer == "DIM-TXT-01    (NEO-A)"


def test_boundary_mask_aligns_with_render(page2):
    doc, page = page2
    scale = 2.0
    mask = boundary_mask(page, scale)
    img = render(doc, 1, scale)
    assert mask.shape == img.shape[:2]
    # Where we draw a boundary, the real sheet must have ink nearby (±2 px: our lines are drawn
    # at least 2 px wide, the sheet's are thin and anti-aliased). Catches rotation/offset bugs.
    ink = (img.mean(axis=2) < 230).astype(np.uint8)
    near_ink = cv2.dilate(ink, np.ones((5, 5), np.uint8)) > 0
    on = mask > 0
    agreement = (near_ink & on).sum() / on.sum()
    assert agreement > 0.9, agreement


def test_rectangles_on_unrotated_pages_rasterize():
    # Rotated pages (gegmebi) went through the quad conversion; unrotated ones passed PyMuPDF's
    # "re" items (plain Rects) straight to rasterize(), which crashed on them.
    import fitz
    from app.extract import rasterize, read_page
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.draw_rect(fitz.Rect(20, 20, 80, 60), color=(0, 0, 0), width=1)
    data = read_page(doc, 0)
    assert all(it[0] in ("l", "c", "qu") for d in data.drawings for it in d["items"])
    mask = rasterize(data, 1.0)
    assert mask[20, 50] > 0 and mask[40, 50] == 0  # outline drawn, inside empty
