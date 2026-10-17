"""Derivative sheets drawn on the architect's own sheet, the way the album does it.

The source page is placed unchanged (vectors, title block, everything) on a new page in display
orientation, and our layer goes on top as vectors, with a legend in an empty corner of the
drawing and the title block extended:
- occupancy: diagonal hatch and dashed outline per zone; "დაკავებულობის გეგმა", ა-100 → ა-100(ა)
- fire: red 2-hour / blue 1-hour dash-dot rated walls; "ხანძარსაწინააღმდეგო გეგმა", ა-100(ბ)
- accessibility: route bands and turning circles; "მისაწვდომობის გეგმა", ა-100(გ)
"""

import os
import re
from dataclasses import dataclass, field

import cv2
import fitz
import numpy as np

from .extract import PageData
from .access import accessible_routes, door_clearances
from .egress import egress_paths
from .fire import fire_lines
from .zones import ZoneResult

FONT_FILE = os.environ.get("SHEET_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_NAME = "sheetfont"

# Album colors (DownloadServlet (1).pdf occupancy layer), residential darkened a little — pure
# yellow hairlines nearly vanish once the sheet is rasterized for the report.
CLASS_STYLE = {
    # Album colours: residential pure yellow, business lavender (sampled from the architects' sheets).
    "residential": {"rgb": (0.94, 0.94, 0.0), "code": "სც-2", "ka": "საცხოვრებელი ჯგუფი", "en": "Residential group"},
    "business": {"rgb": (0.55, 0.38, 0.85), "code": "სქ", "ka": "საქმიანი ჯგუფი", "en": "Business group"},
    "mercantile": {"rgb": (0.85, 0.35, 0.0), "code": "სვ", "ka": "სავაჭრო ჯგუფი", "en": "Mercantile group"},
    "assembly": {"rgb": (0.8, 0.1, 0.45), "code": "თვ", "ka": "თავშეყრის ჯგუფი", "en": "Assembly group"},
    "institutional": {"rgb": (0.0, 0.55, 0.6), "code": "დწ", "ka": "დაწესებულებითი ჯგუფი", "en": "Institutional group"},
    "educational": {"rgb": (0.2, 0.6, 0.2), "code": "სგ", "ka": "საგანმანათლებლო ჯგუფი", "en": "Educational group"},
    "factory": {"rgb": (0.55, 0.35, 0.15), "code": "სმ", "ka": "სამრეწველო ჯგუფი", "en": "Factory group"},
    # Codes from rulebook №41 ch. 3 (storage is სწ — not "სნ").
    "storage": {"rgb": (0.53, 0.53, 0.53), "code": "სწ", "ka": "სასაწყობო ჯგუფი", "en": "Storage group"},
    "parking": {"rgb": (0.35, 0.35, 0.35), "code": "სწ-2", "ka": "ავტოსადგომი", "en": "Parking"},
}
SHEET_SUFFIX = {"occupancy": "(ა)", "fire": "(ბ)", "accessibility": "(გ)"}
SHEET_TITLE = {
    "occupancy": {"ka": "დაკავებულობის გეგმა", "en": "Occupancy plan"},
    "fire": {"ka": "ხანძარსაწინააღმდეგო გეგმა", "en": "Fire safety plan"},
    "accessibility": {"ka": "მისაწვდომობის გეგმა", "en": "Accessibility plan"},
}
LEGEND_TITLE = {
    "occupancy": {"ka": "დაკავებულობის ჯგუფები", "en": "Occupancy groups"},
    "fire": {"ka": "ხანძარმედეგობა", "en": "Fire resistance"},
    "accessibility": {"ka": "მისაწვდომობა", "en": "Accessibility"},
}
# Album colors and wording (DownloadServlet (1).pdf fire sheets, ა-10Xc).
FIRE_STYLE = {
    "2h": {"rgb": (0.92, 0.0, 0.0), "ka": "2 სთ-იანი ხანძარმედეგობა", "en": "2-hour fire resistance"},
    "1h": {"rgb": (0.0, 0.0, 1.0), "ka": "1 სთ-იანი ხანძარმედეგობა", "en": "1-hour fire resistance"},
    # Sprinklered residential corridors only (Table 1018.1); the album has no such line.
    "0.5h": {"rgb": (0.75, 0.0, 0.75), "ka": "0.5 სთ-იანი ხანძარმედეგობა", "en": "½-hour fire resistance"},
}
RATED_WIDTH_PT = 1.4
# Album route grey (0.81) is drawn under the plan there; ours goes on top, so darker and translucent.
ROUTE_RGB = (0.45, 0.45, 0.45)
ROUTE_OPACITY = 0.45
EGRESS_RGB = (0.13, 0.55, 0.13)  # album green
EGRESS_LABEL = {"ka": "ევაკუაციის უდიდესი სავალი მანძილი", "en": "Longest escape travel distance"}
CLEARANCE_RGB = (0.32, 0.57, 0.65)  # album teal
ACCESS_LABELS = {
    "route": {"ka": "მისაწვდომი მარშრუტი (≥0.9 მ)", "en": "Accessible route (≥0.9 m)"},
    "clearance": {"ka": "კარის მანევრირების სივრცე (1.5 მ)", "en": "Door manoeuvring space (1.5 m)"},
    "circle": {"ka": "მობრუნების წრე Ø1.5 მ", "en": "Turning circle Ø1.5 m"},
}

HATCH_SPACING_PT = 3.5
HATCH_WIDTH_PT = 0.35
OUTLINE_WIDTH_PT = 0.9
# The album lays a light tint of the zone colour under the hatch and outlines the zone in a darker
# shade of it, solid — hatch alone on white read as faint and odd.
TINT_OPACITY = 0.14
OUTLINE_SHADE = 0.65
SHEET_NUMBER = re.compile(r"^[ა-ჰA-Za-z]{1,3}-\d{2,4}[ა-ჰa-z]?$")
AREA_VALUE = re.compile(r"^\d+[.,]\d{1,2}$")
TITLE_KEYWORD = re.compile(r"გეგმ|plan|план", re.IGNORECASE)
# The title block is the right-hand strip of the sheet on every set we've seen.
TITLE_STRIP_X = 0.78


@dataclass
class UnitTag:
    name: str
    cls: str
    area_m2: float | None          # unit area printed beside its name on the sheet
    measured_m2: float | None      # floor area of the unit's rooms measured from geometry


@dataclass
class SheetResult:
    doc: fitz.Document = field(repr=False)
    sheet_number: str | None
    derived_number: str | None
    title_lines: list[str]
    units: list[UnitTag]
    classes: list[str]
    egress_m: list[float] = field(default_factory=list)  # longest escape routes drawn (occupancy)


def _font() -> fitz.Font:
    return fitz.Font(fontfile=FONT_FILE)


def _text(page: fitz.Page, x: float, baseline: float, text: str, size: float, color=(0, 0, 0)) -> None:
    page.insert_text((x, baseline), text, fontsize=size, fontname=FONT_NAME, fontfile=FONT_FILE, color=color)


# ── geometry → vectors ────────────────────────────────────────────────────────────────────────

def hatch_segments(mask: np.ndarray, scale: float, spacing_pt: float = HATCH_SPACING_PT):
    """'/' hatch lines (x + y = c in image space) clipped to the mask, as point segments."""
    h, w = mask.shape
    inside = mask > 0
    step = spacing_pt * scale * np.sqrt(2)  # perpendicular spacing → spacing along the x axis
    segs = []
    for c in np.arange(step / 2, w + h, step):
        c = int(round(c))
        x = np.arange(max(0, c - h + 1), min(w, c + 1))
        if x.size < 2:
            continue
        y = c - x
        v = inside[y, x].astype(np.int8)
        d = np.diff(np.concatenate(([0], v, [0])))
        for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1):
            if b - a < 2:
                continue
            segs.append(((x[a] / scale, y[a] / scale), (x[b] / scale, y[b] / scale)))
    return segs


def outline_polys(mask: np.ndarray, scale: float, min_area_pt2: float = 30.0):
    contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    polys = []
    for c in contours:
        if cv2.contourArea(c) / scale / scale < min_area_pt2:
            continue
        c = cv2.approxPolyDP(c, 0.6, True)
        polys.append([(float(p[0][0]) / scale, float(p[0][1]) / scale) for p in c])
    return polys


def _draw_hatch(page: fitz.Page, segs, rgb, width=HATCH_WIDTH_PT) -> None:
    shape = page.new_shape()
    for a, b in segs:
        shape.draw_line(a, b)
    shape.finish(color=rgb, width=width, lineCap=1)
    shape.commit()


def _shade(rgb, k=OUTLINE_SHADE):
    return tuple(c * k for c in rgb)


def _draw_tint(page: fitz.Page, polys, rgb) -> None:
    shape = page.new_shape()
    for poly in polys:
        if len(poly) >= 3:
            shape.draw_polyline(poly + [poly[0]])
    shape.finish(color=None, fill=rgb, fill_opacity=TINT_OPACITY, even_odd=True, closePath=True)
    shape.commit()


def _draw_outline(page: fitz.Page, polys, rgb) -> None:
    shape = page.new_shape()
    for poly in polys:
        if len(poly) >= 3:
            shape.draw_polyline(poly + [poly[0]])
    shape.finish(color=_shade(rgb), width=OUTLINE_WIDTH_PT, lineJoin=1, closePath=False)
    shape.commit()


def _draw_rated_lines(page: fitz.Page, polys, rgb) -> None:
    """Dash-dot lines like the album's fire-resistance lines."""
    shape = page.new_shape()
    for poly in polys:
        if len(poly) >= 2:
            shape.draw_polyline(poly)
    shape.finish(color=rgb, width=RATED_WIDTH_PT, dashes="[6 1.5 1 1.5] 0", lineCap=0, lineJoin=1, closePath=False)
    shape.commit()


def _draw_egress(page: fitz.Page, paths) -> None:
    """Escape routes: solid green line, a dot at the far end, the length beside the dot."""
    for p in paths:
        shape = page.new_shape()
        shape.draw_polyline(p.points)
        shape.finish(color=EGRESS_RGB, width=1.2, lineCap=1, lineJoin=1, closePath=False)
        x, y = p.points[0]
        shape.draw_circle((x, y), 1.6)
        shape.finish(color=EGRESS_RGB, fill=EGRESS_RGB)
        shape.commit()
        label = f"{p.length_m:.1f} მ"
        w = _font().text_length(label, fontsize=5.5)
        page.draw_rect(fitz.Rect(x + 2.5, y - 7, x + 5.5 + w, y - 0.5), color=None, fill=(1, 1, 1), fill_opacity=0.85)
        _text(page, x + 4, y - 2, label, 5.5, color=EGRESS_RGB)


def _draw_band(page: fitz.Page, polys) -> None:
    shape = page.new_shape()
    for poly in polys:
        if len(poly) >= 3:
            shape.draw_polyline(poly + [poly[0]])
    shape.finish(color=None, fill=ROUTE_RGB, fill_opacity=ROUTE_OPACITY, even_odd=True, closePath=True)
    shape.commit()


def _draw_circles(page: fitz.Page, circles) -> None:
    shape = page.new_shape()
    for cx, cy, r in circles:
        shape.draw_circle((cx, cy), r)
    shape.finish(color=(0, 0, 0), width=0.6, dashes="[2 1] 0")
    shape.commit()


# ── title block ───────────────────────────────────────────────────────────────────────────────

def _lines(words) -> list[list]:
    """Words grouped into text lines (same top edge ±1 pt), top to bottom, left to right."""
    lines: list[list] = []
    for w in sorted(words, key=lambda w: (w.bbox[1], w.bbox[0])):
        if lines and abs(lines[-1][0].bbox[1] - w.bbox[1]) <= 1.0:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.bbox[0]) for line in lines]


def title_block(page: PageData):
    """(sheet-title lines as word lists, sheet-number word) read from the title strip."""
    strip = [w for w in page.words if w.bbox[0] > page.width * TITLE_STRIP_X]
    numbers = [w for w in strip if SHEET_NUMBER.match(w.display)]
    number = max(numbers, key=lambda w: w.bbox[1]) if numbers else None

    lines = _lines(strip)
    start = next((i for i, line in enumerate(lines)
                  if any(TITLE_KEYWORD.search(w.display) for w in line) and line[0].size >= 5), None)
    if start is None:
        return [], number
    block = [lines[start]]
    for line in lines[start + 1:]:
        prev = block[-1][0]
        same_size = abs(line[0].size - prev.size) < 0.3
        if same_size and line[0].bbox[1] - prev.bbox[1] < 1.3 * prev.size \
                and any(len(w.display) > 1 for w in line):
            block.append(line)
        else:
            break
    return block, number


def _rewrite_title(out: fitz.Page, page: PageData, kind: str, lang: str):
    block, number = title_block(page)
    title_lines = [" ".join(w.display for w in line) for line in block]
    derived = None
    font = _font()
    if block and kind in SHEET_TITLE:
        text = SHEET_TITLE[kind][lang]
        size = block[0][0].size
        spacing = (block[-1][0].bbox[1] - block[0][0].bbox[1]) / (len(block) - 1) if len(block) > 1 else 1.13 * size
        x0 = min(w.bbox[0] for line in block for w in line)
        x1 = max(w.bbox[2] for line in block for w in line)
        top = block[-1][0].bbox[1] + spacing
        width = font.text_length(text, fontsize=size)
        _text(out, (x0 + x1) / 2 - width / 2, top + 0.8 * size, text, size)
        title_lines.append(text)
    if number is not None:
        derived = number.display + SHEET_SUFFIX[kind]
        x0, y0, x1, y1 = number.bbox
        out.draw_rect(fitz.Rect(x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5), color=None, fill=(1, 1, 1), overlay=True)
        size = number.size
        room = page.width - 12 - x0  # keep clear of the sheet frame
        while font.text_length(derived, fontsize=size) > room and size > 4:
            size -= 0.25
        _text(out, x0, y0 + 0.8 * number.size, derived, size)
    return title_lines, number.display if number else None, derived


# ── placement ─────────────────────────────────────────────────────────────────────────────────

def _ink_map(doc: fitz.Document, index: int, scale: float) -> np.ndarray:
    pix = doc[index].get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    return (gray < 235).astype(np.uint8)


def find_empty_box(ink: np.ndarray, scale: float, w_pt: float, h_pt: float, x_max_pt: float,
                   margin_pt: float = 8.0) -> tuple[float, float] | None:
    """Top-left corner (pt) of an ink-free box, as close to the drawing area's top-right as possible."""
    pad = max(1, int(margin_pt * scale))
    grown = cv2.dilate(ink, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8))
    integral = cv2.integral(grown).astype(np.int64)
    bw, bh = int(np.ceil(w_pt * scale)), int(np.ceil(h_pt * scale))
    H, W = grown.shape
    x_lim = min(W, int(x_max_pt * scale))
    if x_lim - bw <= 0 or H - bh <= 0:
        return None
    sums = (integral[bh:, bw:] - integral[:-bh, bw:] - integral[bh:, :-bw] + integral[:-bh, :-bw])
    sums = sums[:H - bh, :x_lim - bw]
    ys, xs = np.nonzero(sums == 0)
    if ys.size == 0:
        return None
    score = (x_lim - bw - xs) + ys
    i = int(np.argmin(score))
    return xs[i] / scale, ys[i] / scale


# ── legend ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LegendRow:
    label: str
    rgb: tuple[float, float, float]
    style: str  # "hatch" (zone swatch), "line" (rated-wall line), "solid" (escape route), "fill", "circle"


def _class_label(cls: str, lang: str) -> str:
    st = CLASS_STYLE[cls]
    return st[lang] + (f" ({st['code']})" if st["code"] else "")


def _legend_size(title: str, rows: list[LegendRow]) -> tuple[float, float]:
    font = _font()
    text_w = max([font.text_length(r.label, fontsize=6) for r in rows] + [font.text_length(title, fontsize=6.5)])
    return 6 + 26 + 5 + text_w + 6, 6 + 10 + 11 * len(rows) + 3


def _draw_legend(out: fitz.Page, x: float, y: float, title: str, rows: list[LegendRow]) -> None:
    w, h = _legend_size(title, rows)
    out.draw_rect(fitz.Rect(x, y, x + w, y + h), color=(0, 0, 0), fill=(1, 1, 1), width=0.6)
    _text(out, x + 6, y + 6 + 6.5, title, 6.5)
    out.draw_line((x, y + 16), (x + w, y + 16), color=(0, 0, 0), width=0.4)
    for i, row in enumerate(rows):
        top = y + 16 + 4 + 11 * i
        sw = fitz.Rect(x + 6, top, x + 32, top + 7)
        if row.style == "hatch":
            swatch = np.full((int(sw.height * 4), int(sw.width * 4)), 255, np.uint8)
            segs = [((a[0] + sw.x0, a[1] + sw.y0), (b[0] + sw.x0, b[1] + sw.y0))
                    for a, b in hatch_segments(swatch, 4.0, spacing_pt=2.2)]
            out.draw_rect(sw, color=None, fill=row.rgb, fill_opacity=TINT_OPACITY)
            _draw_hatch(out, segs, row.rgb, width=0.5)
            out.draw_rect(sw, color=_shade(row.rgb), width=0.6)
        elif row.style == "line":
            mid = (sw.y0 + sw.y1) / 2
            _draw_rated_lines(out, [[(sw.x0, mid), (sw.x1, mid)]], row.rgb)
        elif row.style == "solid":
            mid = (sw.y0 + sw.y1) / 2
            out.draw_line((sw.x0, mid), (sw.x1, mid), color=row.rgb, width=1.2)
            out.draw_circle((sw.x0 + 1.5, mid), 1.4, color=row.rgb, fill=row.rgb)
        elif row.style == "box":
            out.draw_rect(fitz.Rect(sw.x0 + 6, sw.y0, sw.x1 - 6, sw.y1), color=row.rgb, width=0.7)
        elif row.style == "fill":
            out.draw_rect(sw, color=None, fill=row.rgb, fill_opacity=ROUTE_OPACITY)
        else:
            _draw_circles(out, [((sw.x0 + sw.x1) / 2, (sw.y0 + sw.y1) / 2, sw.height / 2)])
        _text(out, sw.x1 + 5, top + 5.5, row.label, 6)


def _place_legend(out: fitz.Page, src: fitz.Document, index: int, page: PageData,
                  title: str, rows: list[LegendRow]) -> None:
    lw, lh = _legend_size(title, rows)
    ink_scale = 1.0
    spot = find_empty_box(_ink_map(src, index, ink_scale), ink_scale, lw, lh, x_max_pt=page.width * TITLE_STRIP_X)
    if spot:
        _draw_legend(out, spot[0], spot[1], title, rows)


# ── the sheet ─────────────────────────────────────────────────────────────────────────────────

def printed_unit_area(page: PageData, anchor: str) -> float | None:
    """The number printed right after a unit name on the same line: "ბინა-02 185.2" → 185.2."""
    parts = anchor.split()  # "ბინა-02" or "ოფისი 1"
    for w in page.words:
        if w.display != parts[0]:
            continue
        cy, x1 = w.center[1], w.bbox[2]
        line = sorted((v for v in page.words if abs(v.center[1] - cy) < 2 and v.bbox[0] >= x1 - 0.5),
                      key=lambda v: v.bbox[0])
        if len(parts) > 1:  # skip the unit number word
            if not line or line[0].display != parts[1] or line[0].bbox[0] - x1 > 6:
                continue
            x1, line = line[0].bbox[2], line[1:]
        # Single glyphs in between are table-cell dividers (a symbol-font "A" on gegmebi).
        for v in line:
            if v.bbox[0] - x1 > 20 or (len(v.display) > 1 and not AREA_VALUE.match(v.display)):
                break
            if AREA_VALUE.match(v.display):
                return float(v.display.replace(",", "."))
    return None


def unit_tags(page: PageData, zones: ZoneResult) -> list[UnitTag]:
    m2_per_pt2 = (25.4 / 72 / 1000 * zones.drawing_scale) ** 2 if zones.drawing_scale else None
    tags = []
    for anchor, rids in zones.units.items():
        if not rids:
            continue
        measured = sum(zones.rooms[r].area_pt2 for r in rids) * m2_per_pt2 if m2_per_pt2 else None
        tags.append(UnitTag(anchor, zones.unit_class[anchor], printed_unit_area(page, anchor),
                            round(measured, 1) if measured else None))
    return tags


def _base_page(src: fitz.Document, index: int) -> fitz.Document:
    out_doc = fitz.open()
    out_doc.insert_pdf(src, from_page=index, to_page=index)
    # Bake the page rotation into the content so page coordinates == display coordinates, the
    # space our zone masks and words are in (show_pdf_page did not keep the orientation).
    out_doc[0].remove_rotation()
    return out_doc


def occupancy_sheet(src: fitz.Document, index: int, page: PageData, zones: ZoneResult,
                    zone_scale: float, lang: str = "ka") -> SheetResult:
    out_doc = _base_page(src, index)
    out = out_doc[0]

    classes = [c for c in CLASS_STYLE if c in zones.masks and zones.masks[c].any()]
    for cls in classes:
        rgb = CLASS_STYLE[cls]["rgb"]
        polys = outline_polys(zones.masks[cls], zone_scale)
        _draw_tint(out, polys, rgb)
        _draw_hatch(out, hatch_segments(zones.masks[cls], zone_scale), rgb)
        _draw_outline(out, polys, rgb)

    # No tags of our own: units are found by their printed name, and the sheets print the unit
    # area right beside it ("ბინა-02 | 185.2") — the album keeps that as the zone tag.
    tags = unit_tags(page, zones)

    # Longest escape routes (green), on residential floors only — the rules behind them are
    # validated there (same condition as the fire/accessibility sheets).
    residential = [u for u, r in zones.units.items() if r and zones.unit_class[u] == "residential"]
    egress = egress_paths(page, zones, zone_scale) if len(residential) * 2 >= len([1 for r in zones.units.values() if r]) else []
    _draw_egress(out, egress)

    if classes:
        rows = [LegendRow(_class_label(c, lang), CLASS_STYLE[c]["rgb"], "hatch") for c in classes]
        if egress:
            rows.append(LegendRow(EGRESS_LABEL[lang], EGRESS_RGB, "solid"))
        _place_legend(out, src, index, page, LEGEND_TITLE["occupancy"][lang], rows)

    title_lines, number, derived = _rewrite_title(out, page, "occupancy", lang)
    result = SheetResult(out_doc, number, derived, title_lines, tags, classes)
    result.egress_m = [round(p.length_m, 1) for p in egress]
    return result


def fire_sheet(src: fitz.Document, index: int, page: PageData, zones: ZoneResult,
               zone_scale: float, lang: str = "ka", storeys: int | None = None,
               sprinklered: bool = False) -> SheetResult:
    """2-hour (red) and 1-hour (blue) rated walls on the original sheet — see app/fire.py."""
    out_doc = _base_page(src, index)
    out = out_doc[0]
    lines = fire_lines(page, zones, zone_scale, storeys, sprinklered)
    polys = {"2h": lines.two_hour, "1h": lines.one_hour, "0.5h": lines.half_hour}
    classes = [c for c in FIRE_STYLE if polys[c]]
    # 1-hour first so the 2-hour lines stay on top where the two meet.
    for cls in ("0.5h", "1h", "2h"):
        _draw_rated_lines(out, polys[cls], FIRE_STYLE[cls]["rgb"])
    if classes:
        rows = [LegendRow(FIRE_STYLE[c][lang], FIRE_STYLE[c]["rgb"], "line") for c in classes]
        _place_legend(out, src, index, page, LEGEND_TITLE["fire"][lang], rows)
    title_lines, number, derived = _rewrite_title(out, page, "fire", lang)
    return SheetResult(out_doc, number, derived, title_lines, unit_tags(page, zones), classes)


def access_sheet(src: fitz.Document, index: int, page: PageData, zones: ZoneResult,
                 zone_scale: float, lang: str = "ka") -> SheetResult:
    """Accessible route bands and turning circles on the original sheet — see app/access.py."""
    out_doc = _base_page(src, index)
    out = out_doc[0]
    acc = accessible_routes(page, zones, zone_scale)
    classes = []
    if acc.route.any():
        _draw_band(out, outline_polys(acc.route, zone_scale, min_area_pt2=5.0))
        classes.append("route")
    boxes = door_clearances(page, zones, zone_scale)
    if boxes:
        shape = out.new_shape()
        for b in boxes:
            shape.draw_polyline(list(b) + [b[0]])
        shape.finish(color=CLEARANCE_RGB, width=0.7, closePath=True)
        shape.commit()
        classes.append("clearance")
    if acc.circles:
        _draw_circles(out, acc.circles)
        classes.append("circle")
    if classes:
        styles = {"route": ("fill", ROUTE_RGB), "clearance": ("box", CLEARANCE_RGB), "circle": ("circle", (0, 0, 0))}
        rows = [LegendRow(ACCESS_LABELS[c][lang], styles[c][1], styles[c][0]) for c in classes]
        _place_legend(out, src, index, page, LEGEND_TITLE["accessibility"][lang], rows)
    title_lines, number, derived = _rewrite_title(out, page, "accessibility", lang)
    return SheetResult(out_doc, number, derived, title_lines, unit_tags(page, zones), classes)


def to_jpeg(doc: fitz.Document, scale: float = 2.5, quality: int = 85) -> bytes:
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return pix.tobytes("jpeg", jpg_quality=quality)
