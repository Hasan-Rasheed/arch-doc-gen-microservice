"""Room-level score against an answer key from a BIM model (harness/ifc_samples.py): for every
real room, did the pipeline find it as one region, keep it apart from its neighbours, and read
its label? The same measure for any building type, so changes are judged on all of them.

    python -m harness.score_rooms "Samples/Generated - wbdg office"     # every plan with a key

Per plan: found (a region overlaps the room ≥ IOU_FOUND), merged (the region also covers other
rooms), split (no region holds most of the room), labelled (the region's text has the room name).
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from app.extract import open_pdf, read_page
from app.main import ZONE_SCALE, page_verdict
from app.zones import detect_zones

IOU_FOUND = 0.7
MOST = 0.6          # share of a room one region must hold, else the room is "split"


def _room_mask(outlines, shape, scale) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    for pts in outlines:
        if len(pts) >= 3:
            cv2.fillPoly(mask, [np.round(np.array(pts) * scale).astype(np.int32)], 255)
    return mask


def score_plan(pdf: Path, key_path: Path, scale: float = ZONE_SCALE) -> dict:
    key = json.loads(key_path.read_text())
    page = read_page(open_pdf(pdf), 0)
    zones = detect_zones(page, scale) if page.has_layers else None
    verdict, stats = page_verdict(page, zones)
    out = {"plan": pdf.name, "verdict": verdict, "rooms": len(key["rooms"]), **stats}
    if zones is None:
        return {**out, "found": 0, "merged": 0, "split": 0, "labelled": 0}
    labels = zones.labels
    owner = {}  # region id -> key rooms it holds most of
    found = split = labelled = 0
    per_room = []
    for i, room in enumerate(key["rooms"]):
        m = _room_mask(room["outlines"], labels.shape, scale) > 0
        if not m.any():
            continue
        ids, counts = np.unique(labels[m], return_counts=True)
        best = max(((int(r), int(c)) for r, c in zip(ids, counts) if r and r != zones.outside),
                   key=lambda rc: rc[1], default=(0, 0))
        rid, inside = best
        if inside < MOST * m.sum():
            split += 1
            per_room.append({"room": room["name"], "result": "split"})
            continue
        owner.setdefault(rid, []).append(i)
        region = labels == rid
        iou = inside / float((region | m).sum())
        text = " ".join(zones.rooms[rid].words).lower() if rid in zones.rooms else ""
        named = bool(room["name"]) and room["name"].lower().split()[0] in text
        labelled += named
        found += iou >= IOU_FOUND
        per_room.append({"room": room["name"], "iou": round(iou, 2), "labelled": named})
    merged = sum(len(v) for v in owner.values() if len(v) > 1)
    return {**out, "found": found, "merged": merged, "split": split, "labelled": labelled, "detail": per_room}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--out", default="out/score_rooms")
    args = ap.parse_args()
    rows = []
    for folder in args.folders:
        for key in sorted(Path(folder).glob("* key.json")):
            stem = key.name[: -len(" key.json")]
            for variant in ("", " flat", " scan"):
                pdf = key.with_name(f"{stem}{variant}.pdf")
                if pdf.exists():
                    rows.append(score_plan(pdf, key))
    for r in rows:
        n = r["rooms"] or 1
        print(f"{r['plan'][:48]:48} {r['verdict']:26} found {r['found']}/{r['rooms']} ({100 * r['found'] // n}%)"
              f"  merged {r['merged']}  split {r['split']}  labelled {r['labelled']}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "score_rooms.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
