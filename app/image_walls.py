"""Walls from the page image, for drawings without CAD layers: PDFs exported flat, prints to PDF
and scans. The same detector for all of them, because it only looks at what is drawn.

1. Ink: dark pixels, without known text and without letter-sized pieces (scans have no text
   layer, so letters are recognised by their size).
2. Walls: ink at least ~8 cm thick in the building, after closing the space between parallel
   outline lines up to a wall's thickness (outlined and hatched walls), and only long pieces —
   symbols and furniture blobs fall out.
3. Openings: along a wall's line, a gap of any length is bridged where thin lines run through it
   (windows, curtain walls); an empty gap up to a door's width is bridged too (doorways), so
   every room is closed.

Lengths are in the building's metres, converted with the drawing scale (the sheet's "1:100" or
the rooms' written areas; 1:100 when neither is known).

Scored on plans generated from public BIM models (harness/score_rooms.py), flattened and scanned:
KIT office 100% of rooms found, US office 75-85%, TUM hotel 50-79% (2026-10-27).
"""

import cv2
import fitz
import numpy as np

SCALE = 2.0                 # px per point for the wall image
INK_MAX = 150               # grey level: darker is ink
LETTER_MM = 4.0             # ink pieces no bigger than this on paper are letters / small symbols
WALL_THICKNESS_M = 0.32     # parallel outline lines closer than this are one wall
MIN_WALL_M = 0.08           # walls are at least this thick
MIN_PIECE_M = 0.6           # wall pieces are at least this long
GLAZING_M = 8.0             # gaps this long along a wall are bridged where thin lines run through
DOOR_M = 1.2                # empty gaps up to a doorway's width are bridged


def page_gray(page: fitz.Page, scale: float = SCALE) -> np.ndarray:
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()


def _rect(k: tuple[int, int]) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_RECT, (max(1, k[0]), max(1, k[1])))


def wall_mask(gray: np.ndarray, scale: float = SCALE, denom: int | None = None,
              text_boxes: list[tuple[float, float, float, float]] = ()) -> np.ndarray:
    """0/255 wall mask at `scale` px per point; `text_boxes` in points (known text to ignore)."""
    px_per_m = 1000 / (denom or 100) / 25.4 * 72 * scale

    def m(metres: float) -> int:
        return int(round(metres * px_per_m))

    ink = (gray < INK_MAX).astype(np.uint8)
    for x0, y0, x1, y1 in text_boxes:
        ink[max(0, int(y0 * scale) - 1):int(y1 * scale) + 2, max(0, int(x0 * scale) - 1):int(x1 * scale) + 2] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
    small = np.maximum(st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT]) <= LETTER_MM / 25.4 * 72 * scale
    small[0] = False
    ink[small[lab]] = 0

    t = max(3, m(WALL_THICKNESS_M))
    solid = np.maximum(cv2.morphologyEx(ink, cv2.MORPH_CLOSE, _rect((t, 1))),
                       cv2.morphologyEx(ink, cv2.MORPH_CLOSE, _rect((1, t))))
    core = (cv2.distanceTransform(solid, cv2.DIST_L2, 3) >= max(1.5, m(MIN_WALL_M) / 2)).astype(np.uint8)
    walls = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) & solid
    n, lab, st, _ = cv2.connectedComponentsWithStats(walls, 8)
    keep = np.maximum(st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT]) >= m(MIN_PIECE_M)
    keep[0] = False
    walls = keep[lab].astype(np.uint8)

    thin = cv2.dilate(ink, _rect((3, 3)))
    far = m(GLAZING_M)
    for k in ((far, 1), (1, far)):
        bridged = cv2.morphologyEx(walls, cv2.MORPH_CLOSE, _rect(k))
        line = cv2.morphologyEx(thin, cv2.MORPH_OPEN, _rect((k[0] // 8, k[1] // 8)))
        walls = np.maximum(walls, bridged & line)
    gap = m(DOOR_M)
    walls = np.maximum(walls, np.maximum(cv2.morphologyEx(walls, cv2.MORPH_CLOSE, _rect((gap, 1))),
                                         cv2.morphologyEx(walls, cv2.MORPH_CLOSE, _rect((1, gap)))))
    return walls * 255
