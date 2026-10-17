"""Score a predicted occupancy coloring against the architects' answer key.

Both sides are per-class masks in the same display space and scale. Reported per class:
- iou        — overlap / union: the headline number
- precision  — share of our colored pixels that the architects also colored with this class
- recall     — share of the architects' colored pixels we covered
and overall:
- spill      — share of our colored pixels where the architects colored nothing at all
               (color over walls, corridors, site — the client's main complaint)
"""

import numpy as np


def score(pred: dict[str, np.ndarray], truth: dict[str, np.ndarray]) -> dict:
    classes = sorted(set(pred) | set(truth))
    shape = next(iter(truth.values())).shape
    empty = np.zeros(shape, bool)
    any_truth = np.zeros(shape, bool)
    for m in truth.values():
        any_truth |= m > 0
    any_pred = np.zeros(shape, bool)

    per_class = {}
    for c in classes:
        p = pred.get(c, empty) > 0
        t = truth.get(c, empty) > 0
        any_pred |= p
        inter, union = (p & t).sum(), (p | t).sum()
        if not union:
            continue
        per_class[c] = {
            "iou": round(inter / union, 3),
            "precision": round(inter / p.sum(), 3) if p.sum() else None,
            "recall": round(inter / t.sum(), 3) if t.sum() else None,
            "truthPx": int(t.sum()),
            "predPx": int(p.sum()),
        }

    weights = {c: v["truthPx"] for c, v in per_class.items()}
    total = sum(weights.values()) or 1
    mean_iou = sum(per_class[c]["iou"] * w for c, w in weights.items()) / total
    spill = (any_pred & ~any_truth).sum() / any_pred.sum() if any_pred.sum() else 0.0
    return {"meanIoU": round(mean_iou, 3), "spill": round(float(spill), 3), "classes": per_class}
