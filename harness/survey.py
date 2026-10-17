"""Runs the service's page checks over every sample PDF and reports, per page, whether it would
get geometry sheets or fall back to the AI — and why. The answer to "does this work beyond the
one project it was tuned on", measured instead of promised.

    python -m harness.survey --samples "/work/Sample Input Diagrams & Description input"

Writes out/survey/survey.json and prints one line per page plus a per-set summary.
"""

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from app.extract import open_pdf, read_page
from app.main import page_verdict
from app.zones import detect_zones


def sample_set(name: str) -> str:
    """Group files the way they came: gegmebi, the new/ folder, the Master files, the rest."""
    if name.startswith("new/"):
        return "new/"
    if "Master" in name:
        return "Master / Grand Master"
    return name.rsplit(".", 1)[0]


def survey(samples: Path, scale: float = 1.0) -> list[dict]:
    rows = []
    for path in sorted(samples.rglob("*.pdf")):
        name = str(path.relative_to(samples))
        try:
            doc = open_pdf(path)
        except Exception as exc:
            rows.append({"file": name, "set": sample_set(name), "page": None, "verdict": f"unreadable: {exc}"})
            continue
        for i in range(len(doc)):
            t = time.time()
            page = read_page(doc, i)
            zones = detect_zones(page, scale) if page.has_layers else None
            verdict, stats = page_verdict(page, zones)
            rows.append({"file": name, "set": sample_set(name), "page": i + 1, "verdict": verdict,
                         **stats, "seconds": round(time.time() - t, 1)})
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
    ap.add_argument("--samples", required=True)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--out", default="out/survey")
    args = ap.parse_args()
    rows = survey(Path(args.samples), args.scale)
    for r in rows:
        print(f"{r['file'][:38]:38} p{r['page']}  {r['verdict']:28} "
              + " ".join(f"{k}={v}" for k, v in r.items() if k not in ("file", "set", "page", "verdict")))
    print()
    for name, s in summary(rows).items():
        print(f"{name:28} {s['geometry']:3}/{s['pages']:<3} pages get geometry sheets   {s['reasons']}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "survey.json").write_text(json.dumps({"rows": rows, "summary": summary(rows)}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
