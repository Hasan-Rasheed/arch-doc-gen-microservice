"""Second-building answer keys (harness/second_key.py): the keys exist, the raw-plan simulation
removes only derivative graphics, and how far Grand Master 42 gets."""

import pytest

from app.extract import open_pdf, read_page
from app.main import page_verdict
from app.zones import detect_zones
from harness.second_key import KEYS, strip_derivatives, truth
from harness.samples import BOCHORMA_PAGES

SAMPLES = BOCHORMA_PAGES
pytestmark = pytest.mark.skipif(not SAMPLES.exists(), reason="sample PDFs not mounted")


@pytest.fixture(scope="module")
def gm42():
    return read_page(open_pdf(SAMPLES / "42 Grand Master.pdf"), 0)


def test_truth_has_rated_walls_and_route(gm42):
    t = truth(gm42, KEYS[0], 1.0)
    assert (t["rated"] > 0).sum() > 5000 and (t["route"] > 0).sum() > 50000


def test_strip_removes_only_derivative_graphics(gm42):
    raw = strip_derivatives(gm42)
    cats = {gm42.layers[(d.get("layer") or "").strip()].cls.category for d in raw.drawings
            if (d.get("layer") or "").strip() in gm42.layers}
    assert not any(c.startswith("DERIVATIVE") for c in cats)
    assert raw.words == gm42.words and len(raw.drawings) < len(gm42.drawings)


def test_offices_read_and_corridor_joined(gm42):
    """Since N2: offices read by number, the corridor split by glazed partitions joined into one
    circulation zone, and the page passes the occupancy gate (fire/accessibility still fall back
    — see test_api_* and app/main.py)."""
    raw = strip_derivatives(gm42)
    zones = detect_zones(raw, 1.0)
    assert {"ოფისი-#01", "ოფისი-#02", "ოფისი-#03", "ოფისი-#06"} <= set(zones.units)
    corridor = [r for r in zones.rooms.values() if r.circulation and not r.core and r.area_pt2 > 2000]
    assert len(corridor) >= 4
    verdict, stats = page_verdict(raw, zones)
    assert verdict == "ok", stats
