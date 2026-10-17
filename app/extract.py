"""Read a vector architectural PDF: layers, drawn geometry per layer, and positioned words.

All coordinates returned here are in DISPLAY space (PDF points, page rotation applied), the
same orientation `page.get_pixmap()` renders and a human sees. PyMuPDF itself reports drawings
and text in unrotated space — gegmebi's sheets are stored rotated 270°, so skipping the
rotation silently puts every label in the wrong place.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import fitz
import numpy as np

from .acadnusx import is_legacy_georgian_font, to_georgian
from .layers import BOUNDARY, LayerClass, classify


@dataclass
class Word:
    text: str                 # as stored in the PDF
    georgian: str | None      # Unicode Georgian when the font is a legacy AcadNusx-family font
    bbox: tuple[float, float, float, float]  # display space
    layer: str                # "" when the text is outside any layer
    font: str
    size: float

    @property
    def display(self) -> str:
        return self.georgian or self.text

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return (x0 + x1) / 2, (y0 + y1) / 2


@dataclass
class LayerInfo:
    name: str
    cls: LayerClass
    paths: int = 0
    texts: int = 0


@dataclass
class PageData:
    index: int
    width: float
    height: float
    rotation: int
    has_layers: bool
    layers: dict[str, LayerInfo]
    words: list[Word]
    drawings: list[dict] = field(repr=False)  # PyMuPDF drawings, points already in display space
    layer_source: str = "pdf"  # "pdf" (CAD layers) or "style" (recognised by line style, styles.py)


def open_pdf(source: str | Path | bytes) -> fitz.Document:
    if isinstance(source, bytes):
        return fitz.open(stream=source, filetype="pdf")
    return fitz.open(str(source))


def _to_display(page: fitz.Page):
    m = page.rotation_matrix
    return lambda p: fitz.Point(p) * m


def _words_from_trace(page: fitz.Page) -> list[Word]:
    """Build words from text-trace spans (they carry layer + font; get_text("words") doesn't)."""
    to_disp = _to_display(page)
    words: list[Word] = []
    for span in page.get_texttrace():
        font = span.get("font", "")
        legacy = is_legacy_georgian_font(font)
        layer = (span.get("layer") or "").strip()
        current: list[tuple[str, tuple]] = []

        def flush():
            if not current:
                return
            text = "".join(c for c, _ in current)
            rect = fitz.Rect()
            for _, b in current:
                r = fitz.Rect(b)
                # Zero-area glyph boxes (spaces, some CAD fonts) would collapse the union.
                rect |= r if not r.is_empty else fitz.Rect(r.x0, r.y0, r.x0 + 0.01, r.y0 + 0.01)
            quad = fitz.Quad(to_disp(rect.tl), to_disp(rect.tr), to_disp(rect.bl), to_disp(rect.br))
            d = quad.rect
            words.append(Word(text, to_georgian(text) if legacy else None,
                              (d.x0, d.y0, d.x1, d.y1), layer, font, span.get("size", 0.0)))
            current.clear()

        for uc, _gid, _origin, bbox in span["chars"]:
            ch = chr(uc)
            if ch.isspace():
                flush()
            else:
                current.append((ch, bbox))
        flush()
    return words


def _drawings_to_display(page: fitz.Page) -> list[dict]:
    """Drawings in display space, with rectangles ("re") turned into quads ("qu") so callers
    only ever see "l", "c" and "qu" items — on unrotated pages too (a "re" item holds a Rect,
    which rasterize() can't treat as a quad)."""
    m = page.rotation_matrix
    out = []
    for d in page.get_drawings():
        items = []
        for it in d["items"]:
            kind = it[0]
            if kind == "l":
                items.append(("l", it[1] * m, it[2] * m))
            elif kind == "c":
                items.append(("c", it[1] * m, it[2] * m, it[3] * m, it[4] * m))
            elif kind == "re":
                items.append(("qu", fitz.Rect(it[1]).quad * m))
            elif kind == "qu":
                items.append(("qu", it[1] * m))
        d = dict(d, items=items, rect=fitz.Rect(d["rect"]) * m)
        out.append(d)
    return out


def read_page(doc: fitz.Document, index: int) -> PageData:
    page = doc[index]
    drawings = _drawings_to_display(page)
    words = _words_from_trace(page)

    path_counts = Counter((d.get("layer") or "").strip() for d in drawings)
    text_counts = Counter(w.layer for w in words)
    layers: dict[str, LayerInfo] = {}
    for name in set(path_counts) | set(text_counts):
        layers[name] = LayerInfo(name, classify(name), path_counts.get(name, 0), text_counts.get(name, 0))

    has_layers = bool(doc.get_ocgs()) and any(n for n in layers)
    data = PageData(index, page.rect.width, page.rect.height, page.rotation, has_layers,
                    layers, words, drawings)
    if not has_layers:
        from .styles import style_layers  # no CAD layers: recognise walls by how they're drawn
        data = style_layers(data) or data
    return data


def read_pdf(source: str | Path | bytes) -> list[PageData]:
    doc = open_pdf(source)
    return [read_page(doc, i) for i in range(len(doc))]


# Cubic Bézier basis for 12 samples, computed once: some plans have 250k curves, and building
# it per curve dominated rasterizing them.
_T = np.linspace(0, 1, 12)[:, None]
_BEZIER = np.hstack([(1 - _T) ** 3, 3 * (1 - _T) ** 2 * _T, 3 * (1 - _T) * _T ** 2, _T ** 3])


def _bezier(p0, p1, p2, p3):
    return _BEZIER @ np.array((p0, p1, p2, p3), dtype=float)


def rasterize(page: PageData, scale: float, categories: set[str] | None = None,
              layer_names: set[str] | None = None, min_px: int = 1,
              light_fill_max: float = 0.8) -> np.ndarray:
    """Draw the selected layers' geometry as a binary mask (255 = ink) at `scale` px per point.

    We draw the vectors ourselves instead of toggling PDF layers and rendering, so content with
    no layer, odd OCG visibility settings, and colors can't leak in or out. Fills lighter than
    `light_fill_max` (mean RGB) are skipped as wipeouts; raise it to keep light-grey fills.
    """
    # Same pixel size PyMuPDF uses for get_pixmap, so masks and renders always line up.
    ir = (fitz.Rect(0, 0, page.width, page.height) * fitz.Matrix(scale, scale)).irect
    mask = np.zeros((ir.height, ir.width), np.uint8)
    for d in page.drawings:
        name = (d.get("layer") or "").strip()
        info = page.layers.get(name)
        if layer_names is not None and name not in layer_names:
            continue
        if categories is not None and (info is None or info.cls.category not in categories):
            continue
        thick = max(min_px, int(round((d.get("width") or 0) * scale)))
        polys: list[np.ndarray] = []
        cur: list = []
        for it in d["items"]:
            if it[0] == "l":
                seg = [tuple(it[1]), tuple(it[2])]
            elif it[0] == "c":
                seg = [tuple(p) for p in _bezier(*(tuple(p) for p in it[1:5]))]
            else:  # quad
                q = it[1]
                polys.append(np.array([tuple(q.ul), tuple(q.ur), tuple(q.lr), tuple(q.ll)]))
                continue
            if cur and abs(cur[-1][0] - seg[0][0]) <= 1e-3 and abs(cur[-1][1] - seg[0][1]) <= 1e-3:
                cur.extend(seg[1:])
            else:
                if cur:
                    polys.append(np.array(cur))
                cur = list(seg)
        if cur:
            polys.append(np.array(cur))
        pts = [np.round(p * scale).astype(np.int32) for p in polys if len(p) >= 2]
        if not pts:
            continue
        fill = d.get("fill")
        # Light fills are CAD "wipeouts" (white masks hiding what's under them), not solid
        # material: on gegmebi's ground floor they cover the whole building interior.
        if fill is not None and d.get("type") in ("f", "fs") and sum(fill[:3]) / 3 < light_fill_max:
            cv2.fillPoly(mask, [p for p in pts if len(p) >= 3], 255)
        stroke = d.get("color")
        # White/near-white strokes are invisible on paper (wipeout frames) — not walls.
        visible_stroke = stroke is None or sum(stroke[:3]) / 3 < 0.8
        if (d.get("type") in ("s", "fs") or fill is None) and visible_stroke:
            cv2.polylines(mask, pts, bool(d.get("closePath")), 255, thick)
    return mask


def boundary_mask(page: PageData, scale: float) -> np.ndarray:
    """Room boundaries: walls, columns, doors, windows, rails, and wall mass (hatch/solid fill)."""
    return rasterize(page, scale, BOUNDARY | {"WALL_FILL"}, min_px=2)


def render(doc: fitz.Document, index: int, scale: float) -> np.ndarray:
    """The page as a human sees it (RGB), at `scale` px per point."""
    pix = doc[index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()


def summary(page: PageData) -> dict:
    """JSON-friendly page summary (no raw geometry) for the API and for debugging."""
    by_cat: dict[str, list[str]] = defaultdict(list)
    for info in page.layers.values():
        by_cat[info.cls.category].append(info.name)
    return {
        "index": page.index,
        "width": page.width,
        "height": page.height,
        "rotation": page.rotation,
        "hasLayers": page.has_layers,
        "layers": [
            {"name": i.name, "category": i.cls.category, "confidence": i.cls.confidence,
             "reason": i.cls.reason, "paths": i.paths, "texts": i.texts}
            for i in sorted(page.layers.values(), key=lambda i: -i.paths)
        ],
        "layersByCategory": dict(by_cat),
        "words": [
            {"text": w.text, "display": w.display, "bbox": [round(v, 2) for v in w.bbox],
             "layer": w.layer, "font": w.font}
            for w in page.words
        ],
    }
