"""Predict occupancy zones for every answer-key sheet and score them.

    python -m harness.run_zones --source "<input.pdf>" --key out/answer_key --out out/zones

Needs `harness.build` to have produced the answer key first (same --scale).
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from app.extract import open_pdf, read_page, render
from app.zones import detect_zones
from harness.build import preview
from harness.score import score


def diff_image(img: np.ndarray, pred: dict, truth: dict) -> np.ndarray:
    """Green = both colored the same class, red = we colored where they didn't (spill),
    blue = they colored where we didn't (missed)."""
    out = (img * 0.5 + 127).astype(np.uint8)
    shape = img.shape[:2]
    p_any, t_any, agree = np.zeros(shape, bool), np.zeros(shape, bool), np.zeros(shape, bool)
    for c in set(pred) | set(truth):
        p = pred.get(c, np.zeros(shape, np.uint8)) > 0
        t = truth.get(c, np.zeros(shape, np.uint8)) > 0
        p_any |= p
        t_any |= t
        agree |= p & t
    out[agree] = (60, 170, 60)
    out[p_any & ~agree] = (220, 40, 40)
    out[t_any & ~p_any] = (40, 90, 220)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--key", default="out/answer_key")
    ap.add_argument("--out", default="out/zones")
    args = ap.parse_args()

    key = Path(args.key)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = json.loads((key / "summary.json").read_text())
    scale = summary["scale"]
    doc = open_pdf(args.source)

    results = []
    for sheet in summary["sheets"]:
        src = sheet["sourcePage"] - 1
        stem = f"target_p{sheet['targetPage']:02d}_source_p{src + 1:02d}"
        truth = {}
        for cls in ("residential", "business", "storage"):
            f = key / f"{stem}_{cls}.png"
            if f.exists():
                truth[cls] = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)

        page = read_page(doc, src)
        z = detect_zones(page, scale)
        s = score(z.masks, truth)
        img = render(doc, src, scale)
        cv2.imwrite(str(out / f"{stem}_pred.jpg"), cv2.cvtColor(preview(img, z.masks), cv2.COLOR_RGB2BGR))
        cv2.imwrite(str(out / f"{stem}_diff.jpg"), cv2.cvtColor(diff_image(img, z.masks, truth), cv2.COLOR_RGB2BGR))

        bad_areas = [c for c in z.area_checks if c["ratio"] and not 0.85 <= c["ratio"] <= 1.15]
        results.append({
            "targetPage": sheet["targetPage"], "sourcePage": src + 1,
            "score": s, "rectangleBaseline": sheet["baselines"]["perfectRectangles"]["meanIoU"],
            "units": {a: {"class": z.unit_class[a], "rooms": len(r)} for a, r in z.units.items()},
            "drawingScale": z.drawing_scale,
            "areaChecks": {"total": len(z.area_checks), "outside15pct": bad_areas},
        })
        print(f"p{sheet['targetPage']} (input p{src + 1}): meanIoU {s['meanIoU']} spill {s['spill']} "
              f"[rectangles {results[-1]['rectangleBaseline']}] | units {list(z.units)} | "
              f"1:{z.drawing_scale} area checks {len(z.area_checks) - len(bad_areas)}/{len(z.area_checks)} ok")

    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    mean = sum(r["score"]["meanIoU"] for r in results) / max(1, len(results))
    print(f"MEAN meanIoU over {len(results)} sheets: {mean:.3f}")


if __name__ == "__main__":
    main()
