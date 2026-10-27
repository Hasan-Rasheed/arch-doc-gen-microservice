"""Runs the service's page checks over every sample PDF and reports, per page, whether it would
get geometry sheets or fall back to the AI — and why. The answer to "does this work beyond the
one project it was tuned on", measured instead of promised.

    python -m harness.survey            # every input under Samples/ (albums left out)
    python -m harness.survey --classes harness/room_classes.json   # + the LLM's room classes

With --classes, a failed page with unknown room names is checked again with the classifier's
answers, as the backend does (classifyRoomNames → /sheets retry). The file holds the LLM's real
answers ({room name: class}), refreshed by the backend script `npm run classify:samples`.

Writes out/survey/survey.json and prints one line per page plus a per-set summary.
"""

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from app.extract import open_pdf, read_page
from app.acadnusx import fold
from app.main import page_verdict, unclassified_names
from app.zones import detect_zones
from harness.samples import SAMPLES, inputs, project


def survey(samples: Path = SAMPLES, scale: float = 1.0, classes: dict[str, str] | None = None) -> list[dict]:
    rows = []
    for path in inputs(samples):
        name = str(path.relative_to(samples))
        try:
            doc = open_pdf(path)
        except Exception as exc:
            rows.append({"file": name, "set": project(path, samples), "page": None, "verdict": f"unreadable: {exc}"})
            continue
        for i in range(len(doc)):
            t = time.time()
            page = read_page(doc, i)
            zones = detect_zones(page, scale) if page.has_layers else None
            verdict, stats = page_verdict(page, zones)
            unknown = unclassified_names(zones) if zones is not None and verdict != "ok" else []
            classified = False
            if unknown and classes:
                folded = {fold(k): v for k, v in classes.items()}
                zones = detect_zones(page, scale, folded)
                verdict, stats = page_verdict(page, zones)
                classified = True
            rows.append({"file": name, "set": project(path, samples), "page": i + 1, "verdict": verdict,
                         **stats, "classified": classified, "unknown": unknown,
                         "seconds": round(time.time() - t, 1)})
    return rows


def summary(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"pages": 0, "geometry": 0, "reasons": defaultdict(int)})
    for r in rows:
        s = out[r["set"]]
        s["pages"] += 1
        if r["verdict"] == "ok":
            s["geometry"] += 1
        else:
            s["reasons"][r["verdict"]] += 1
    return {k: {**v, "reasons": dict(v["reasons"])} for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(SAMPLES))
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--classes", help="JSON {room name: class} from the LLM")
    ap.add_argument("--out", default="out/survey")
    args = ap.parse_args()
    classes = json.loads(Path(args.classes).read_text()) if args.classes else None
    rows = survey(Path(args.samples), args.scale, classes)
    for r in rows:
        print(f"{r['file'][:38]:38} p{r['page']}  {r['verdict']:28} "
              + " ".join(f"{k}={v}" for k, v in r.items() if k not in ("file", "set", "page", "verdict", "unknown")))
    print()
    for name, s in summary(rows).items():
        print(f"{name:32} {s['geometry']:3}/{s['pages']:<3} pages get geometry sheets   {s['reasons']}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "survey.json").write_text(json.dumps({"rows": rows, "summary": summary(rows)}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
