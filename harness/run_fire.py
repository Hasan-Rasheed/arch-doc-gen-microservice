"""Runs app/fire.py on every fire answer-key sheet (album p.39-44), scores it, writes previews.

    python -m harness.run_fire --target ".../DownloadServlet (1).pdf" --source ".../gegmebi (2).pdf"

Preview colors: truth in light red/blue, prediction in dark red/blue on top.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from app.extract import open_pdf, read_page, render
from app.fire import fire_lines
from app.zones import detect_zones
from .answer_key import match_source_page, to_source_coords
from .fire_key import fire_truth, line_score

FIRE_PAGES = [39, 40, 41, 42, 43, 44]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--out", default="out/fire")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tdoc, sdoc = open_pdf(args.target), open_pdf(args.source)
    sources = [read_page(sdoc, i) for i in range(len(sdoc))]
    results = {}
    for tp in FIRE_PAGES:
        truth = fire_truth(tdoc, tp - 1, args.scale)
        match = match_source_page(read_page(tdoc, tp - 1), sources)
        tmasks = {c: to_source_coords(m, match.offset, args.scale) for c, m in truth.masks.items()}
        page = sources[match.index]
        pred = fire_lines(page, detect_zones(page, args.scale), args.scale)
        s = line_score(pred.masks, tmasks, args.scale)
        results[tp] = {"source": match.index, **s}
        print(tp, "->", match.index, json.dumps(s))

        img = (render(sdoc, match.index, args.scale) * 0.5 + 127).astype(np.uint8)
        thick = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        for cls, light, dark in (("2h", (255, 150, 150), (200, 0, 0)), ("1h", (150, 150, 255), (0, 0, 200))):
            img[cv2.dilate(tmasks[cls], thick) > 0] = light
        for cls, light, dark in (("2h", (255, 150, 150), (200, 0, 0)), ("1h", (150, 150, 255), (0, 0, 200))):
            img[pred.masks[cls] > 0] = dark
        cv2.imwrite(str(out / f"fire-p{tp}.png"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    (out / "results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
