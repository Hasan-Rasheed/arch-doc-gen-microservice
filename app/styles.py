"""Synthetic layers for PDFs exported without CAD layers (14 of the 22 "Master" samples): walls are
recognised by how they're drawn instead of by layer name.

- Solid dark or grey fills of moderate size are wall cut-fill / columns (ARCHICAD poché) →
  WALL_FILL. In Grand Master 45 the grey 0.72 fill is exactly the wall layout, black the columns.
- A stroke weight whose lines mostly run along those fills is the wall outline pen → WALL. That
  keeps grid circles, leaders and furniture (other pens) out. Door swings drawn with the wall pen
  are found later from their arcs (zones._drawn_doors).

Every drawing gets a pseudo layer name ("~fill", "~wall-0.60", "~stroke-0.24"); callers see an
ordinary layered page, and the usual gates still decide whether it's good enough.
"""

from collections import Counter, defaultdict

import cv2
import numpy as np

from .layers import LayerClass

FILL_MAX_GREY = 0.8          # lighter fills are wipeouts / background
FILL_MAX_PAGE_SHARE = 0.05   # a fill bigger than this is a background or site hatch, not a wall
MIN_WALL_FILLS = 20          # fewer: no wall poché to anchor on — give up
MIN_PEN_DRAWINGS = 50
WALL_PEN_ON_FILL = 0.5       # share of a pen's ink within 2 pt of wall fill
SCALE = 0.5


def _wall_fill(d: dict, page_area: float) -> bool:
    fill = d.get("fill")
    if fill is None or d.get("type") not in ("f", "fs"):
        return False
    r = d["rect"]
    return sum(fill[:3]) / 3 < FILL_MAX_GREY and r.width * r.height < FILL_MAX_PAGE_SHARE * page_area


def style_layers(page):
    """A copy of `page` (extract.PageData without layers) with pseudo layers, or None when the
    drawing has no wall fills to recognise walls by."""
    from .extract import LayerInfo, PageData, rasterize

    area = page.width * page.height
    fills = [d for d in page.drawings if _wall_fill(d, area)]
    if len(fills) < MIN_WALL_FILLS:
        return None

    def mask(drawings) -> np.ndarray:
        sub = PageData(page.index, page.width, page.height, page.rotation, False, {}, [], drawings)
        return rasterize(sub, SCALE, min_px=1)

    near_fill = cv2.dilate(mask(fills), np.ones((5, 5), np.uint8)) > 0  # ≈ 2 pt at SCALE 0.5
    pens: dict[float, list[dict]] = defaultdict(list)
    for d in page.drawings:
        if d.get("type") == "s":
            pens[round(d.get("width") or 0, 2)].append(d)
    wall_pens = set()
    for width, ds in pens.items():
        if len(ds) < MIN_PEN_DRAWINGS:
            continue
        ink = mask(ds) > 0
        if ink.any() and (ink & near_fill).sum() / ink.sum() >= WALL_PEN_ON_FILL:
            wall_pens.add(width)

    fill_ids = {id(d) for d in fills}
    drawings, counts = [], Counter()
    for d in page.drawings:
        if id(d) in fill_ids:
            name = "~fill"
        elif d.get("type") == "s":
            w = round(d.get("width") or 0, 2)
            name = f"~wall-{w:.2f}" if w in wall_pens else f"~stroke-{w:.2f}"
        else:
            name = "~other"
        drawings.append(dict(d, layer=name))
        counts[name] += 1

    def cls(name: str) -> LayerClass:
        if name == "~fill":
            return LayerClass("WALL_FILL", "medium", "dark/grey solid fill (no CAD layers)")
        if name.startswith("~wall-"):
            return LayerClass("WALL", "medium", "pen that runs along the wall fills (no CAD layers)")
        return LayerClass("UNKNOWN", "none", "no CAD layers")

    layers = {n: LayerInfo(n, cls(n), c, 0) for n, c in counts.items()}
    layers[""] = LayerInfo("", LayerClass("UNKNOWN", "none", "text without layers"), 0, len(page.words))
    out = PageData(page.index, page.width, page.height, page.rotation, True, layers, page.words, drawings)
    out.layer_source = "style"
    return out
