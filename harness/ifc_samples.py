"""Test inputs from public BIM models: each storey of an IFC model becomes the floor plan an
architect would upload, plus an answer key of its rooms, so the pipeline is measured on many
building types without waiting for real projects of each type.

    # 1) IFC → SVG plans (needs IfcOpenShell; not in the service image)
    PYTHONPATH=/pylib python -m harness.ifc_samples svg  model.ifc out/plans.svg
    # 2) SVG → per storey: <name> - <storey>.pdf (CAD layers), "... flat.pdf" (no layers),
    #    "... scan.pdf" (an image), and "... key.json" (rooms: name, number, area, outline)
    python -m harness.ifc_samples pdf out/plans.svg "Samples/Generated - wbdg office" "wbdg office"

Layers carry ARCHICAD's template names, as in the architects' files we've seen (layers.py knows
them); the plan is drawn by IfcOpenShell at 1:100 with door swings and room labels (name,
number, area), like a working floor plan.
"""

import argparse
import copy
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import fitz

SVG = "http://www.w3.org/2000/svg"
IFC = "http://www.ifcopenshell.org/ns"
ET.register_namespace("", SVG)
ET.register_namespace("ifc", IFC)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
MM = 72 / 25.4

# IFC class → layer name. Room outlines (IfcSpace paths) aren't drawn: real plans show the walls
# and the room's label, not the space boundary.
LAYERS = [
    ("Structural - Bearing", ("IfcWall", "IfcColumn", "IfcCurtainWall", "IfcSlab", "IfcPlate", "IfcMember",
                              "IfcBeam")),
    ("Openings - Doors", ("IfcDoor",)),
    ("Openings - Windows", ("IfcWindow",)),
    ("Interior - Stair & Railing", ("IfcStair", "IfcRailing", "IfcRamp")),
    ("Interior - Furniture", ("IfcFurnishingElement", "IfcFurniture", "IfcFlowTerminal", "IfcSanitaryTerminal")),
    ("Annotation - Text", ("IfcSpace",)),
]


def draw_svg(ifc_path: str, svg_path: str, exclude: str = "") -> None:
    import ifcopenshell
    import ifcopenshell.draw as draw
    # cells=False: the cell post-processing fails in IfcOpenShell 0.9 and isn't needed here.
    settings = draw.draw_settings(auto_floorplan=True, space_names=True, space_areas=True, door_arcs=True,
                                  scale=1 / 100, cells=False,
                                  exclude_entities=",".join(["IfcOpeningElement", *filter(None, exclude.split(","))]))
    Path(svg_path).write_bytes(draw.main(settings, [ifcopenshell.open(ifc_path)]))


def _classes(g: ET.Element) -> set[str]:
    return set(g.get("class", "").split())


def _layer_of(g: ET.Element) -> str | None:
    cls = _classes(g)
    for name, prefixes in LAYERS:
        if any(c.startswith(p) for c in cls for p in prefixes):
            return name
    return None


def _clean_text(root: ET.Element) -> None:
    """Plan-size labels and line door swings. Set on the elements: MuPDF's SVG reader doesn't
    apply added CSS rules."""
    for t in root.iter(f"{{{SVG}}}tspan"):
        if t.text:
            t.text = t.text.replace("&#178;", "²").replace("m²", " m²")
    # One <text> per label line, at its own y: MuPDF joins tspans of one <text> into one word
    # ("OFFICE11427.54") when the PDF's text is read back.
    for parent in root.iter(f"{{{SVG}}}g"):
        for t in list(parent.findall(f"{{{SVG}}}text")):
            spans = t.findall(f"{{{SVG}}}tspan")
            x, y = float(t.get("x", 0)), float(t.get("y", 0))
            idx = list(parent).index(t)
            parent.remove(t)
            dy_mm, line_mm = -0.65 * float(TEXT_MM), float(TEXT_MM)
            for k, span in enumerate(spans):
                line = ET.Element(f"{{{SVG}}}text", {"x": f"{x}", "y": f"{y + dy_mm + k * line_mm}",
                                                     "text-anchor": t.get("text-anchor", "middle"),
                                                     "font-size": TEXT_MM, "font-family": "sans-serif"})
                line.text = span.text
                parent.insert(idx + k, line)
    for g in root.iter(f"{{{SVG}}}g"):
        if "IfcDoor" in _classes(g):
            for path in g.iter(f"{{{SVG}}}path"):
                path.set("style", "fill:none;stroke:#000;stroke-width:0.18")


# Room labels at plan-text size (the drawing is in mm at 1:100: 2.2 = 2.2 mm on paper).
TEXT_MM = "2.2"
MARGIN_MM = 15


def _extent(storey: ET.Element) -> tuple[float, float, float, float]:
    """Bounding box (mm) of everything drawn on the storey."""
    pts = [pt for p in storey.iter(f"{{{SVG}}}path") for pt in _points(p.get("d", ""))]
    xs, ys = [x / MM for x, _ in pts], [y / MM for _, y in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _storey_svg(root: ET.Element, storey: ET.Element, layer: str) -> bytes:
    """The page with only this storey's elements of one layer, cropped to the storey's drawing."""
    doc = copy.deepcopy(root)
    x0, y0, x1, y1 = _extent(storey)
    w, h = x1 - x0 + 2 * MARGIN_MM, y1 - y0 + 2 * MARGIN_MM
    doc.set("viewBox", f"{x0 - MARGIN_MM} {y0 - MARGIN_MM} {w} {h}")
    doc.set("width", f"{w}mm")
    doc.set("height", f"{h}mm")
    for g in list(doc):
        if g.tag == f"{{{SVG}}}g" and "IfcBuildingStorey" in _classes(g) and g.get("id") != storey.get("id"):
            doc.remove(g)
    for st in doc.iter(f"{{{SVG}}}g"):
        if st.get("id") != storey.get("id"):
            continue
        for g in list(st):
            if _layer_of(g) != layer:
                st.remove(g)
            elif layer == "Annotation - Text":
                for p in list(g.findall(f"{{{SVG}}}path")):
                    g.remove(p)
    return ET.tostring(doc)


def _points(d: str) -> list[tuple[float, float]]:
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d)]
    return [(nums[i] * MM, nums[i + 1] * MM) for i in range(0, len(nums) - 1, 2)]


def _key(storey: ET.Element) -> list[dict]:
    """Rooms with their outlines in PDF points on the cropped page."""
    x0, y0, _, _ = _extent(storey)
    ox, oy = (x0 - MARGIN_MM) * MM, (y0 - MARGIN_MM) * MM
    rooms = []
    for g in storey:
        if "IfcSpace" not in _classes(g):
            continue
        lines = [t.text or "" for t in g.iter(f"{{{SVG}}}text")]
        area = next((float(m.group(1)) for l in lines if (m := re.search(r"([\d.]+)\s*m", l))), None)
        paths = [p.get("d", "") for p in g.findall(f"{{{SVG}}}path")]
        rooms.append({"name": lines[0] if lines else "", "number": g.get(f"{{{IFC}}}name"), "areaM2": area,
                      "outlines": [[(x - ox, y - oy) for x, y in _points(d)] for d in paths if d]})
    return rooms


def write_pdfs(svg_path: str, out_dir: str, title: str) -> list[Path]:
    root = ET.parse(svg_path).getroot()
    _clean_text(root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for storey in [g for g in root if "IfcBuildingStorey" in _classes(g)]:
        name = storey.get(f"{{{IFC}}}name") or storey.get("id")
        key = _key(storey)
        if not key:
            continue  # roofs and empty levels: no rooms to check
        stem = f"{title} - {re.sub(r'[^0-9A-Za-z._ -]+', '_', name)}"
        for flat in (False, True):
            doc = fitz.open()
            page = None
            ocgs = {} if flat else {layer: doc.add_ocg(layer, on=True) for layer, _ in LAYERS}
            for layer, _ in LAYERS:
                src = fitz.open(stream=_storey_svg(root, storey, layer), filetype="svg")
                pdf = fitz.open("pdf", src.convert_to_pdf())
                if page is None:
                    page = doc.new_page(width=pdf[0].rect.width, height=pdf[0].rect.height)
                page.show_pdf_page(page.rect, pdf, 0, oc=ocgs.get(layer, 0))
            label_oc = ocgs.get("Annotation - Text", 0)
            page.insert_text((40, page.rect.height - 40), f"{title} — {name}    M 1:100", fontsize=10, oc=label_oc)
            path = out / f"{stem}{' flat' if flat else ''}.pdf"
            doc.save(path, garbage=3, deflate=True)
            made.append(path)
            if flat:
                pix = page.get_pixmap(dpi=150, colorspace=fitz.csGRAY)
                scan = fitz.open()
                sp = scan.new_page(width=page.rect.width, height=page.rect.height)
                sp.insert_image(sp.rect, pixmap=pix)
                scan.save(out / f"{stem} scan.pdf", deflate=True)
                made.append(out / f"{stem} scan.pdf")
        (out / f"{stem} key.json").write_text(json.dumps({"storey": name, "rooms": key}, ensure_ascii=False))
    return made


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("svg")
    s.add_argument("ifc")
    s.add_argument("svg")
    s.add_argument("--exclude", default="", help="extra IFC classes to leave out (heavy models: "
                                                   "IfcFurnishingElement,IfcBuildingElementProxy)")
    p = sub.add_parser("pdf")
    p.add_argument("svg")
    p.add_argument("out_dir")
    p.add_argument("title")
    args = ap.parse_args()
    if args.cmd == "svg":
        draw_svg(args.ifc, args.svg, args.exclude)
    else:
        for path in write_pdfs(args.svg, args.out_dir, args.title):
            print(path)


if __name__ == "__main__":
    sys.exit(main())
