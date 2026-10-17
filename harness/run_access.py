"""Runs app/access.py on every accessibility answer-key sheet (album p.33-38), scores it, writes
previews: truth band light grey, predicted band dark, turning circles black.

    python -m harness.run_access --target ".../DownloadServlet (1).pdf" --source ".../gegmebi (2).pdf"
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from app.access import accessible_routes
from app.extract import open_pdf, read_page, render
from app.zones import detect_zones
from .answer_key import match_source_page, to_source_coords
from .fire_key import access_truth, area_score

ACCESS_PAGES = [33, 34, 35, 36, 37, 38]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--out", default="out/access")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tdoc, sdoc = open_pdf(args.target), open_pdf(args.source)
    sources = [read_page(sdoc, i) for i in range(len(sdoc))]
    results = {}
    for tp in ACCESS_PAGES:
        match = match_source_page(read_page(tdoc, tp - 1), sources)
        truth = to_source_coords(access_truth(tdoc, tp - 1, args.scale), match.offset, args.scale)
        page = sources[match.index]
        pred = accessible_routes(page, detect_zones(page, args.scale), args.scale)
        s = area_score(pred.route, truth, args.scale)
        results[tp] = {"source": match.index, **s, "circles": len(pred.circles)}
        print(tp, "->", match.index, json.dumps(results[tp]))

        img = (render(sdoc, match.index, args.scale) * 0.5 + 127).astype(np.uint8)
        img[truth > 0] = (200, 200, 200)
        img[pred.route > 0] = (img[pred.route > 0] * 0.4).astype(np.uint8)
        for cx, cy, r in pred.circles:
            cv2.circle(img, (int(cx * args.scale), int(cy * args.scale)), int(r * args.scale), (0, 0, 0), 2)
        cv2.imwrite(str(out / f"access-p{tp}.png"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    (out / "results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
