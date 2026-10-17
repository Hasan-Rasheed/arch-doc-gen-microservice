"""Build ground truth from an architect-made album whose derivative sheets are on CAD layers.

DownloadServlet (1).pdf draws its occupancy plans on the layer `-------DAKAVEBULOBIS GEGMA` as
colored hatch LINES with no outline (yellow = residential სც, purple = business/office სქ),
plus black zone-tag tables and green escape-route travel-distance polylines. We turn the hatch
lines back into solid regions, one mask per occupancy class, and match each sheet to the input
page it was drawn over.
"""

from dataclasses import dataclass

import cv2
import fitz
import numpy as np

from app.extract import PageData, rasterize, read_page

# Hatch line colors (RGB 0-1) on the architects' occupancy layer -> class. Tolerance 0.08.
OCCUPANCY_COLORS = {
    "residential": (1.0, 1.0, 0.0),
    "business": (0.31, 0.05, 0.73),
    "storage": (0.53, 0.53, 0.53),
}
EGRESS_COLOR = (0.13, 0.55, 0.13)


def _color_of(d: dict) -> tuple[float, ...]:
    return tuple(d.get("fill") or d.get("color") or ())


def _close(c1, c2, tol=0.08) -> bool:
    return len(c1) == len(c2) == 3 and all(abs(a - b) <= tol for a, b in zip(c1, c2))


def _layer_subset(page: PageData, keep) -> PageData:
    return PageData(page.index, page.width, page.height, page.rotation, page.has_layers,
                    page.layers, [], [d for d in page.drawings if keep(d)])


def _category(page: PageData, d: dict) -> str | None:
    info = page.layers.get((d.get("layer") or "").strip())
    return info.cls.category if info else None


def building_extent(page: PageData, scale: float, pad_pt: float = 15) -> np.ndarray:
    """Mask of the drawing area around the building (from wall/column geometry), used to drop
    legend swatches and title-block content that share the derivative layers."""
    walls = rasterize(page, scale, {"COLUMN", "WALL", "FINISH_EXT"}, min_px=2)
    ys, xs = np.nonzero(walls)
    out = np.zeros_like(walls)
    if len(xs):
        p = int(pad_pt * scale)
        out[max(0, ys.min() - p):ys.max() + p, max(0, xs.min() - p):xs.max() + p] = 255
    return out


MIN_REGION_PT2 = 800  # ≈ 2 m² at 1:200; legend swatches are ~250 pt², real rooms are larger


def hatch_to_region(lines: np.ndarray, scale: float) -> np.ndarray:
    """Hatch lines -> solid region: close the gaps between hatch strokes, drop thin leftovers
    (leader lines, single strokes) with an opening, then drop tiny pieces (legend swatches)."""
    k = max(3, int(round(6 * scale)) | 1)          # hatch spacing is ~3-4 pt on these sheets
    closed = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    o = max(3, int(round(3 * scale)) | 1)
    region = cv2.morphologyEx(closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (o, o)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats((region > 0).astype(np.uint8))
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= MIN_REGION_PT2 * scale * scale
    return np.where(keep[labels], 255, 0).astype(np.uint8)


@dataclass
class OccupancyTruth:
    page_index: int
    title: str
    masks: dict[str, np.ndarray]      # class -> 0/255 mask, display space at `scale`
    egress: np.ndarray                 # travel-distance polylines
    scale: float


def occupancy_truth(doc: fitz.Document, index: int, scale: float) -> OccupancyTruth | None:
    page = read_page(doc, index)
    occ = lambda d: _category(page, d) == "DERIVATIVE_OCCUPANCY"
    if not any(occ(d) for d in page.drawings):
        return None
    extent = building_extent(page, scale)
    masks = {}
    for cls, rgb in OCCUPANCY_COLORS.items():
        sub = _layer_subset(page, lambda d, rgb=rgb: occ(d) and _close(_color_of(d), rgb))
        region = hatch_to_region(rasterize(sub, scale, min_px=2), scale)
        masks[cls] = cv2.bitwise_and(region, extent)
    egress = rasterize(_layer_subset(page, lambda d: occ(d) and _close(_color_of(d), EGRESS_COLOR)), scale, min_px=2)
    return OccupancyTruth(index, sheet_title(page), masks, cv2.bitwise_and(egress, extent), scale)


def sheet_title(page: PageData) -> str:
    """Title-block text (bottom-right of the sheet), decoded to Georgian."""
    words = [w for w in page.words if w.bbox[0] > page.width * 0.8 and 0.80 * page.height < w.bbox[1] < 0.92 * page.height]
    return " ".join(w.display for w in words)


def _shift(mask: np.ndarray, dx_px: float, dy_px: float) -> np.ndarray:
    m = np.float32([[1, 0, dx_px], [0, 1, dy_px]])
    return cv2.warpAffine(mask, m, (mask.shape[1], mask.shape[0]), flags=cv2.INTER_NEAREST)


@dataclass
class SourceMatch:
    index: int            # 0-based input page index, -1 if none
    iou: float            # wall/column overlap after aligning
    offset: tuple[float, float]  # (dx, dy) in points: target coords + offset = source coords


def match_source_page(target: PageData, sources: list[PageData], scale: float = 0.5) -> SourceMatch:
    """Which input page a derivative sheet was drawn over, and how far the architects moved the
    view when plotting it (same drawing, translated — seen on DownloadServlet (1).pdf p.28)."""
    t = rasterize(target, scale, {"COLUMN", "WALL"}, min_px=2)
    tf = cv2.GaussianBlur(t.astype(np.float32), (0, 0), 3)
    best = SourceMatch(-1, 0.0, (0.0, 0.0))
    for s in sources:
        if (s.width, s.height) != (target.width, target.height):
            continue
        m = rasterize(s, scale, {"COLUMN", "WALL"}, min_px=2)
        (dx, dy), _ = cv2.phaseCorrelate(tf, cv2.GaussianBlur(m.astype(np.float32), (0, 0), 3))
        candidates = [(0.0, 0.0), (dx, dy)]
        for cdx, cdy in candidates:
            moved = _shift(t, cdx, cdy) > 0
            mm = m > 0
            union = (moved | mm).sum()
            iou = (moved & mm).sum() / union if union else 0.0
            if iou > best.iou:
                best = SourceMatch(s.index, float(iou), (cdx / scale, cdy / scale))
    return best


def to_source_coords(mask: np.ndarray, offset_pt: tuple[float, float], scale: float) -> np.ndarray:
    return _shift(mask, offset_pt[0] * scale, offset_pt[1] * scale)
