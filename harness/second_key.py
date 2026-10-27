"""Answer keys from other offices' sheets, to check that what was tuned on gegmebi carries over.

These samples are the architects' finished derivative sheets: the plan plus their own fire /
accessibility markup on dedicated layers. Removing those layers' graphics gives the raw plan our
pipeline would receive (room text is kept — labels are part of any plan), and the markup is the
truth to score against.

    python -m harness.second_key

- Sample 1 / 42 Grand Master (Bochorma №11 office floor): rated walls (blue on "41"/"000-41"; 1-hour
  and 2-hour differ only in dash rhythm, so they're scored together) + accessible route (light-
  blue fills).
- Ardstudio LLC - Sample 2 (clinic): 2-hour wall lines (blue on "!კედლის საათები - 2 საათი") + accessible route.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.access import accessible_routes
from app.extract import PageData, open_pdf, rasterize, read_page
from app.fire import fire_lines
from app.main import page_verdict
from app.zones import detect_zones
from .answer_key import _close, _color_of, _layer_subset, building_extent
from .fire_key import area_score, line_score
from harness.samples import SAMPLES


def _layer(d: dict) -> str:
    return (d.get("layer") or "").strip()


def strip_derivatives(page: PageData) -> PageData:
    """The plan as it was before the architects added their derivative markup."""
    keep = [d for d in page.drawings
            if not (page.layers.get(_layer(d)) and page.layers[_layer(d)].cls.category.startswith("DERIVATIVE"))]
    return PageData(page.index, page.width, page.height, page.rotation, page.has_layers,
                    page.layers, page.words, keep)


@dataclass
class Key:
    file: str
    page: int                 # 1-based
    rated_layers: tuple[str, ...]
    rated_rgb: tuple[float, float, float]
    route_layer_word: str     # substring of the accessibility layer name
    route_rgb: tuple[float, float, float]


CLINIC = "Ardstudio LLC - Sample 2"
KEYS = [
    Key("Sample 1/42 Grand Master.pdf", 1, ("41", "000-41"), (0.0, 0.0, 1.0), "misawvdomoba", (0.5, 0.76, 1.0)),
    *[Key(f, 1, ("!კედლის საათები - 2 საათი - ლაინებში",), (0.0, 0.0, 1.0), "მისაწვდომობა", (0.69, 0.69, 0.71))
      for f in (f"{CLINIC}/2. -1    -25,05,26.pdf", f"{CLINIC}/3. 1  25,05,26.pdf", f"{CLINIC}/4. 2   25,05,26.pdf",
                f"{CLINIC}/5. 3.pdf", f"{CLINIC}/7. 5.pdf")],
]


def truth(page: PageData, key: Key, scale: float) -> dict[str, np.ndarray]:
    extent = building_extent(page, scale)
    rated = _layer_subset(page, lambda d: _layer(d) in key.rated_layers and _close(_color_of(d), key.rated_rgb))
    route = _layer_subset(page, lambda d: key.route_layer_word in _layer(d) and d.get("type") in ("f", "fs")
                          and _close(_color_of(d), key.route_rgb))
    return {
        "rated": cv2.bitwise_and(rasterize(rated, scale, min_px=2), extent),
        "route": cv2.bitwise_and(rasterize(route, scale, light_fill_max=0.9), extent),
    }


def evaluate(samples: Path, key: Key, scale: float) -> dict:
    page = read_page(open_pdf(samples / key.file), key.page - 1)
    t = truth(page, key, scale)
    raw = strip_derivatives(page)
    zones = detect_zones(raw, scale)
    verdict, stats = page_verdict(raw, zones)
    fire = fire_lines(raw, zones, scale)
    rated = cv2.bitwise_or(fire.masks["2h"], fire.masks["1h"])
    route = accessible_routes(raw, zones, scale).route
    return {
        "file": key.file, "verdict": verdict, **stats,
        "truthPx": {k: int((v > 0).sum()) for k, v in t.items()},
        "rated": line_score({"rated": rated}, {"rated": t["rated"]}, scale)["rated"],
        "route": area_score(route, t["route"], scale),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(SAMPLES))
    ap.add_argument("--scale", type=float, default=2.0)  # the service's ZONE_SCALE
    ap.add_argument("--out", default="out/second_key")
    args = ap.parse_args()
    rows = [evaluate(Path(args.samples), k, args.scale) for k in KEYS]
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
