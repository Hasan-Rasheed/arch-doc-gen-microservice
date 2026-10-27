"""Every sample PDF through the service's page checks (harness/survey.py) — the regression test
for "works beyond the project it was tuned on". Slow (~10 min: the new/ pages are heavy), so it
only runs with RUN_SURVEY=1.

When a change makes more pages work, raise the floor in MIN_GEOMETRY_PAGES.
"""
import os
import pytest

from harness.samples import SAMPLES
from harness.survey import summary, survey

pytestmark = [
    pytest.mark.skipif(not SAMPLES.exists(), reason="sample PDFs not mounted"),
    pytest.mark.skipif(os.environ.get("RUN_SURVEY") != "1", reason="slow; set RUN_SURVEY=1"),
]

# Pages per sample set that must get geometry sheets (at the time of writing).
MIN_GEOMETRY_PAGES = {"Gegmebi - Sample 3": 6}


@pytest.fixture(scope="module")
def rows():
    return survey(SAMPLES)


def test_no_page_crashes(rows):
    assert not [r for r in rows if r["verdict"].startswith(("error", "unreadable"))]


def test_geometry_floor_per_set(rows):
    s = summary(rows)
    for name, minimum in MIN_GEOMETRY_PAGES.items():
        assert s[name]["geometry"] >= minimum, s[name]


def test_fallback_pages_say_why(rows):
    reasons = {"ok", "no CAD layers", "no units found", "zones not closed by walls", "most rooms not in units"}
    assert {r["verdict"] for r in rows} <= reasons
