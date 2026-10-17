"""Build the occupancy answer key from the architects' album and score reference baselines.

    python -m harness.build --target "<album.pdf>" --source "<input.pdf>" --out out/answer_key

Writes, per occupancy sheet: one PNG mask per class, a preview overlay, and summary.json with
the matched input page and baseline scores.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from app.extract import open_pdf, read_page, render
from harness.answer_key import match_source_page, occupancy_truth, to_source_coords
from harness.score import score

PREVIEW_RGB = {"residential": (240, 200, 0), "business": (110, 40, 190), "storage": (130, 130, 130)}


def rectangles_of(mask: np.ndarray) -> np.ndarray:
    """Each connected region replaced by its axis-aligned bounding box — the best a
    rectangle-based coloring (today's LLM output style) could possibly do."""
    out = np.zeros_like(mask)
    n, _, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8))
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        out[y:y + h, x:x + w] = 255
    return out


def preview(img: np.ndarray, masks: dict[str, np.ndarray], egress: np.ndarray | None = None) -> np.ndarray:
    out = (img * 0.55 + 115).astype(np.uint8)
    for cls, m in masks.items():
        tint = np.array(PREVIEW_RGB.get(cls, (220, 0, 0)), np.uint8)
        sel = m > 0
        out[sel] = (out[sel] * 0.45 + tint * 0.55).astype(np.uint8)
    if egress is not None:
        out[egress > 0] = (20, 140, 20)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", default="out/answer_key")
    ap.add_argument("--scale", type=float, default=2.0)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tdoc, sdoc = open_pdf(args.target), open_pdf(args.source)
    sources = [read_page(sdoc, i) for i in range(len(sdoc))]

    sheets = []
    for i in range(len(tdoc)):
        truth = occupancy_truth(tdoc, i, args.scale)
        if truth is None or not any((m > 0).any() for m in truth.masks.values()):
            continue
        match = match_source_page(read_page(tdoc, i), sources)
        # Everything below is in the INPUT page's coordinates, so predictions made on the input
        # page can be scored directly.
        masks = {c: to_source_coords(m, match.offset, args.scale) for c, m in truth.masks.items()}
        egress = to_source_coords(truth.egress, match.offset, args.scale)
        stem = f"target_p{i + 1:02d}_source_p{match.index + 1:02d}"
        for cls, m in masks.items():
            if (m > 0).any():
                cv2.imwrite(str(out / f"{stem}_{cls}.png"), m)
        cv2.imwrite(str(out / f"{stem}_egress.png"), egress)
        img = render(sdoc, match.index, args.scale)
        cv2.imwrite(str(out / f"{stem}_preview.jpg"), cv2.cvtColor(preview(img, masks, egress), cv2.COLOR_RGB2BGR))

        rects = {c: rectangles_of(m) for c, m in masks.items()}
        sheets.append({
            "targetPage": i + 1,
            "title": truth.title,
            "sourcePage": match.index + 1,
            "sourceMatchIoU": round(match.iou, 3),
            "offsetPt": [round(v, 2) for v in match.offset],
            "truthPx": {c: int((m > 0).sum()) for c, m in masks.items()},
            "baselines": {
                "truthVsItself": score(masks, masks)["meanIoU"],
                "perfectRectangles": score(rects, masks),
            },
        })
        print(f"p{i + 1}: {truth.title[:60]} -> source p{match.index + 1} (IoU {match.iou:.2f}, offset {match.offset[0]:.1f},{match.offset[1]:.1f} pt); "
              f"rectangles meanIoU {sheets[-1]['baselines']['perfectRectangles']['meanIoU']}, "
              f"spill {sheets[-1]['baselines']['perfectRectangles']['spill']}")

    (out / "summary.json").write_text(json.dumps({"scale": args.scale, "sheets": sheets}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
