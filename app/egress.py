"""Longest escape-route travel distance, the green lines on the album's occupancy sheets: from the
point of a unit farthest from an exit stair, through the unit's door and along the corridor, to
that stair. One line per exit stair whose longest route is at least LONG_SHARE of the floor's
longest (album: one line on most floors, two on −2 where each stair serves a different block).
"""

from dataclasses import dataclass

import cv2
import numpy as np

from .access import ROUTE_SCALE, _dijkstra, _trace, walk_grid
from .extract import PageData
from .fire import SHAFT_WORDS, _has
from .zones import ZoneResult

LONG_SHARE = 0.6
DETOUR_RATIO = 3.0   # route longer than 3× the straight line to a stair we couldn't reach
EXIT_REACH_M = 1.0   # the walkable band next to a stair core where a route ends


@dataclass
class EgressPath:
    points: list[tuple[float, float]]   # polyline in points, from the farthest point to the exit
    length_m: float


def egress_paths(page: PageData, zones: ZoneResult, scale: float) -> list[EgressPath]:
    g = walk_grid(page, zones, scale)
    # Exits are stairs; a lift is not an escape route.
    exits = [rid for rid in g.cores if not _has(zones.rooms[rid], SHAFT_WORDS)]
    unit_rooms = [rid for rid, r in zones.rooms.items() if r.unit]
    if not exits or not unit_rooms:
        return []
    in_units = np.isin(g.labels, unit_rooms) & np.isfinite(g.cost)
    r = max(3, int(EXIT_REACH_M * g.m * ROUTE_SCALE) | 1)

    per_exit, cut_off = [], []
    for rid in exits:
        near = cv2.dilate((g.labels == rid).astype(np.uint8), np.ones((r, r), np.uint8)) > 0
        sources = near & np.isfinite(g.cost)
        d_p = _dijkstra(g.cost, sources) if sources.any() else None
        if d_p is not None and np.isfinite(d_p[0][in_units]).any():
            per_exit.append(d_p)
        else:
            cut_off.append(rid)   # no unit reaches it: a door we didn't read, or a stair not used here
    if not per_exit:
        return []
    # Straight-line distance (m) to each cut-off stair, to catch detours below.
    to_cut = [cv2.distanceTransform((g.labels != rid).astype(np.uint8), cv2.DIST_L2, 5) / ROUTE_SCALE / g.m
              for rid in cut_off]
    dists = np.stack([d for d, _ in per_exit])            # exits × H × W
    nearest = np.argmin(dists, axis=0)
    best = np.min(dists, axis=0)

    paths = []
    for e, (_, pred) in enumerate(per_exit):
        mine = in_units & (nearest == e) & np.isfinite(best)
        if not mine.any():
            continue
        y, x = np.unravel_index(int(np.argmax(np.where(mine, best, -1))), best.shape)
        pix = _trace(pred, (int(y), int(x)))
        if len(pix) < 2:
            continue
        pts = np.array([(px, py) for py, px in pix], np.float32)
        steps = np.hypot(*np.diff(pts, axis=0).T)
        length_m = float(steps.sum() / ROUTE_SCALE / g.m)
        # A stair we couldn't reach is far closer than the route we found: we missed its door
        # (gegmebi −2), and this "longest route" is a detour — a false travel distance. Skip it.
        if any(t[y, x] * DETOUR_RATIO < length_m for t in to_cut):
            continue
        simple = cv2.approxPolyDP(pts.reshape(-1, 1, 2), 1.0, False).reshape(-1, 2)
        paths.append(EgressPath([(float(px) / ROUTE_SCALE, float(py) / ROUTE_SCALE) for px, py in simple], length_m))
    if not paths:
        return []
    longest = max(p.length_m for p in paths)
    return sorted((p for p in paths if p.length_m >= LONG_SHARE * longest), key=lambda p: -p.length_m)


def egress_mask(paths: list[EgressPath], shape: tuple[int, int], scale: float, width_pt: float = 1.4) -> np.ndarray:
    m = np.zeros(shape, np.uint8)
    for p in paths:
        cv2.polylines(m, [np.round(np.array(p.points) * scale).astype(np.int32)], False, 255,
                      max(1, int(round(width_pt * scale))))
    return m
