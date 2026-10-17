"""Ground truth for fire-resistance lines from the architects' album (DownloadServlet (1).pdf
p.39-44, ა-10Xc): 2-hour walls are red on layer "41", 1-hour walls blue on the fire layer
("--------SAXANDZRO_GEGMA"), both drawn as dash pieces. The same layers also carry equipment
symbols and legend samples, which are dropped by size and by the building extent.
Accessible-route bands (p.33-38) are further below."""

from dataclasses import dataclass

import cv2
import fitz
import numpy as np

from app.extract import PageData, rasterize, read_page
from .answer_key import _close, _color_of, _layer_subset, building_extent

RED_2H = (0.92, 0.0, 0.0)
BLUE_1H = (0.0, 0.0, 1.0)
LINE_PX_PT = 1.2         # rasterized line width
JOIN_PT = 6.0            # dash gaps up to this are bridged when grouping pieces into lines
MIN_LINE_EXTENT_PT = 25  # equipment boxes at doors are ~5-10 pt; real fire lines run along walls


def _layer(d: dict) -> str:
    return (d.get("layer") or "").strip()


def _lines(page: PageData, keep, scale: float) -> np.ndarray:
    mask = rasterize(_layer_subset(page, keep), scale, min_px=max(1, int(round(LINE_PX_PT * scale))))
    k = max(3, int(round(JOIN_PT * scale)) | 1)
    joined = cv2.dilate(mask, np.ones((k, k), np.uint8))
    n, comp, stats, _ = cv2.connectedComponentsWithStats((joined > 0).astype(np.uint8))
    keep_ids = [i for i in range(1, n)
                if max(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]) - k >= MIN_LINE_EXTENT_PT * scale]
    return np.where(np.isin(comp, keep_ids) & (mask > 0), 255, 0).astype(np.uint8)


@dataclass
class FireTruth:
    index: int
    masks: dict[str, np.ndarray]   # "2h" / "1h" -> 0/255 line mask
    scale: float


def fire_truth(doc: fitz.Document, index: int, scale: float) -> FireTruth:
    page = read_page(doc, index)
    extent = building_extent(page, scale)
    red = _lines(page, lambda d: _layer(d) == "41" and _close(_color_of(d), RED_2H), scale)
    blue = _lines(page, lambda d: "SAXANDZRO" in _layer(d) and _close(_color_of(d), BLUE_1H), scale)
    return FireTruth(index, {"2h": cv2.bitwise_and(red, extent), "1h": cv2.bitwise_and(blue, extent)}, scale)


def line_score(pred: dict[str, np.ndarray], truth: dict[str, np.ndarray], scale: float, tol_pt: float = 5.0) -> dict:
    """Per class: precision = share of predicted line within tol of a true line of that class,
    recall = share of true line within tol of a predicted one. Lines are compared by position,
    not by pixels, since a wall's line can sit on either face of the wall."""
    k = max(3, int(round(2 * tol_pt * scale)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    out = {}
    for cls, t in truth.items():
        p = pred.get(cls, np.zeros_like(t))
        tp, pp = (t > 0), (p > 0)
        near_t = cv2.dilate(t, kernel) > 0
        near_p = cv2.dilate(p, kernel) > 0
        prec = (pp & near_t).sum() / pp.sum() if pp.any() else None
        rec = (tp & near_p).sum() / tp.sum() if tp.any() else None
        out[cls] = {"precision": None if prec is None else round(float(prec), 3),
                    "recall": None if rec is None else round(float(rec), 3)}
    return out


# ── accessibility (album p.33-38, ა-10Xb) ────────────────────────────────────────────────────

ROUTE_GREY = (0.81, 0.81, 0.81)


def access_truth(doc: fitz.Document, index: int, scale: float) -> np.ndarray:
    """Accessible-route bands: light-grey fills on the accessibility layer (kept despite being
    lighter than our wipeout cutoff)."""
    page = read_page(doc, index)
    sub = _layer_subset(page, lambda d: "MISACV" in _layer(d) and _close(_color_of(d), ROUTE_GREY)
                        and d.get("type") in ("f", "fs"))
    return cv2.bitwise_and(rasterize(sub, scale, light_fill_max=0.9), building_extent(page, scale))


def area_score(pred: np.ndarray, truth: np.ndarray, scale: float, tol_pt: float = 3.0) -> dict:
    """Band overlap with a little positional slack: precision = predicted band within tol of
    the true band, recall = true band within tol of the predicted one."""
    k = max(3, int(round(2 * tol_pt * scale)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    p, t = pred > 0, truth > 0
    prec = (p & (cv2.dilate(truth, kernel) > 0)).sum() / p.sum() if p.any() else None
    rec = (t & (cv2.dilate(pred, kernel) > 0)).sum() / t.sum() if t.any() else None
    return {"precision": None if prec is None else round(float(prec), 3),
            "recall": None if rec is None else round(float(rec), 3)}
