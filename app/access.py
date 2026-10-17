"""Accessible routes from the zones, the way the album's accessibility sheets draw them (ა-10Xb):
a grey band of wheelchair width running from the lift/stair core along the corridor, through
each unit's entrance door and on into its rooms; plus a 1.5 m turning circle in every unit.

Routes are shortest paths through the floor's free space (rooms, corridors and the doorways
between them), costed to keep clear of walls, from the vertical core to the middle of every
named room of every unit.
"""

import heapq
from dataclasses import dataclass

import cv2
import numpy as np

from .acadnusx import folded, starts_with
from .extract import PageData, boundary_mask
from .fire import STAIR, UNIT, _open_air, _space_ids
from .zones import ZoneResult, door_mask

ROUTE_WIDTH_M = 0.9       # band width (clear passage width)
DOOR_PASSAGE_M = 0.25     # half-width of the passage carved along each door
MIN_CLEAR_M = 0.3         # path centre must be at least this far from walls (doors are ~0.9 m)
TURNING_DIAMETER_M = 1.5
ROUTE_SCALE = 0.5         # px per pt for the path search (≈ 0.14 m per px at 1:200)
DEFAULT_DENOM = 200       # drawing scale when the sheet doesn't print one
LIFT_WORDS = folded(("ლიფტ", "lift", "elevator"))


@dataclass
class AccessResult:
    route: np.ndarray                          # band mask at `scale` (0/255)
    circles: list[tuple[float, float, float]]  # turning circles (cx, cy, r) in points
    scale: float


def pt_per_m(zones: ZoneResult) -> float:
    return 1000 / (zones.drawing_scale or DEFAULT_DENOM) / 25.4 * 72


def _dijkstra(cost: np.ndarray, sources: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(cost-weighted distance, predecessor flat index or -1) of every pixel; 8-neighbour moves."""
    h, w = cost.shape
    flat = cost.ravel()
    dist = np.full(h * w, np.inf)
    pred = np.full(h * w, -1, np.int64)
    heap = []
    for s in np.flatnonzero(sources.ravel()):
        dist[s] = 0.0
        heap.append((0.0, int(s)))
    heapq.heapify(heap)
    steps = [(-1, -1, 1.414), (-1, 0, 1.0), (-1, 1, 1.414), (0, -1, 1.0),
             (0, 1, 1.0), (1, -1, 1.414), (1, 0, 1.0), (1, 1, 1.414)]
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist[i]:
            continue
        y, x = divmod(i, w)
        for dy, dx, step in steps:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w:
                j = ny * w + nx
                c = flat[j]
                if not np.isfinite(c):
                    continue
                nd = d + step * (c + flat[i]) / 2
                if nd < dist[j]:
                    dist[j] = nd
                    pred[j] = i
                    heapq.heappush(heap, (nd, j))
    return dist.reshape(h, w), pred.reshape(h, w)


def _trace(pred: np.ndarray, target: tuple[int, int]) -> list[tuple[int, int]]:
    h, w = pred.shape
    i = target[0] * w + target[1]
    path = []
    while i != -1 and len(path) < h * w:
        path.append(divmod(i, w))
        i = pred.flat[i]
    return path


def _pole(region: np.ndarray) -> tuple[tuple[int, int], float]:
    """Point farthest from the region's edges (y, x) and that distance in px."""
    dist = cv2.distanceTransform(region.astype(np.uint8), cv2.DIST_L2, 5)
    y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)
    return (int(y), int(x)), float(dist[y, x])


@dataclass
class WalkGrid:
    """The floor's walkable space on a coarse grid (ROUTE_SCALE px per pt), shared by the
    accessible route and the escape-route lines."""
    small: np.ndarray        # walkable
    cost: np.ndarray         # step cost; inf where not walkable or too tight
    labels: np.ndarray       # room id per grid pixel
    cores: list[int]         # stair/lift core room ids
    m: float                 # points per metre
    shape: tuple[int, int]   # full-resolution (H, W) at the zone scale


def walk_grid(page: PageData, zones: ZoneResult, scale: float) -> WalkGrid:
    m = pt_per_m(zones)
    space_of = _space_ids(zones)
    kinds = {rid: kind for rid, (_, kind) in space_of.items()}
    walk_rooms = [rid for rid, k in kinds.items() if k != STAIR]
    cores = [rid for rid, k in kinds.items() if k == STAIR]
    H, W = zones.labels.shape

    # Walkable: units and corridors, plus doorways (door leaves and swings are drawn on the
    # boundary layers and would otherwise wall every room off).
    walk = np.isin(zones.labels, walk_rooms)
    doors = door_mask(page, scale, m) > 0
    walls = (boundary_mask(page, scale) > 0) & ~doors
    reach = max(3, int(round(0.6 * m * scale)) | 1)
    doorways = cv2.dilate(doors.astype(np.uint8), np.ones((reach, reach), np.uint8)) > 0
    walk |= doorways & ~walls & (zones.labels != zones.outside)
    # A door is passable even where the wall drawing runs across its opening (jambs, a threshold
    # line, a wall hatch): carve a narrow passage along the door itself, exempt from the
    # clearance rule (gegmebi −2: the south stair's only door was otherwise sealed).
    k = max(3, int(round(DOOR_PASSAGE_M * m * scale)) | 1)
    passage = (cv2.dilate(doors.astype(np.uint8), np.ones((k, k), np.uint8)) > 0) & (zones.labels != zones.outside)
    walk |= passage
    walk &= ~np.isin(zones.labels, [rid for rid, r in zones.rooms.items() if _open_air(r)])

    # Search on a coarser grid.
    f = ROUTE_SCALE / scale
    size = (int(W * f), int(H * f))
    small = cv2.resize(walk.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    passage_small = cv2.resize(passage.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    clear = cv2.distanceTransform(small.astype(np.uint8), cv2.DIST_L2, 5) / ROUTE_SCALE / m  # metres
    ok = small & ((clear >= MIN_CLEAR_M) | passage_small)
    cost = np.where(ok, 1.0 + 3.0 * np.clip(1.0 - clear / 0.8, 0, 1), np.inf)
    labels_small = cv2.resize(zones.labels.astype(np.int32), small.shape[::-1], interpolation=cv2.INTER_NEAREST)
    return WalkGrid(small, cost, labels_small, cores, m, (H, W))


def accessible_routes(page: PageData, zones: ZoneResult, scale: float) -> AccessResult:
    g = walk_grid(page, zones, scale)
    small, cost, labels_small, cores, m, (H, W) = g.small, g.cost, g.labels, g.cores, g.m, g.shape
    walls = (boundary_mask(page, scale) > 0) & ~(door_mask(page, scale, m) > 0)

    # Start at the lift if it's labelled, else at the walkable space next to the stair cores.
    labels_small = cv2.resize(zones.labels.astype(np.int32), small.shape[::-1], interpolation=cv2.INTER_NEAREST)
    lift = [w for w in page.words if starts_with(w.display, LIFT_WORDS)]
    sources = np.zeros(small.shape, bool)
    for w in lift:
        cx, cy = int(w.center[0] * ROUTE_SCALE), int(w.center[1] * ROUTE_SCALE)
        r = max(2, int(1.5 * m * ROUTE_SCALE))
        sources[max(0, cy - r):cy + r, max(0, cx - r):cx + r] = True
    if not (sources & np.isfinite(cost)).any() and cores:
        core = np.isin(labels_small, cores).astype(np.uint8)
        r = max(3, int(1.0 * m * ROUTE_SCALE) | 1)
        sources = cv2.dilate(core, np.ones((r, r), np.uint8)) > 0
    sources &= np.isfinite(cost)
    if not sources.any():
        return AccessResult(np.zeros((H, W), np.uint8), [], scale)
    dist, pred = _dijkstra(cost, sources)

    # Targets: the middle of every named room of every unit, if a wheelchair fits there.
    path_px = np.zeros(small.shape, np.uint8)
    for rid, room in zones.rooms.items():
        if not room.unit or not room.has_name or _open_air(room):
            continue
        region = (labels_small == rid) & np.isfinite(cost)
        if not region.any():
            continue
        # The middle of the room, and its far side (the reachable point farthest from the
        # entrance) — the album's bands cross the room rather than stop in its centre.
        far = np.unravel_index(int(np.argmax(np.where(region & np.isfinite(dist), dist, -1))), dist.shape)
        for target in (_pole(region)[0], (int(far[0]), int(far[1]))):
            path = _trace(pred, target)
            if path and sources[path[-1]]:
                for y, x in path:
                    path_px[y, x] = 255

    # Band of route width, back at the zone scale.
    big = cv2.resize(path_px, (W, H), interpolation=cv2.INTER_NEAREST)
    k = max(3, int(round(ROUTE_WIDTH_M * m * scale)) | 1)
    band = cv2.dilate(big, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    band[walls] = 0

    # One turning circle per unit, in its roomiest spot.
    circles = []
    radius_pt = TURNING_DIAMETER_M / 2 * m
    for anchor, rids in zones.units.items():
        named = [r for r in rids if zones.rooms[r].has_name and not _open_air(zones.rooms[r])]
        if not named:
            continue
        (py, px), d = _pole(np.isin(zones.labels, named))
        if d / scale >= radius_pt:
            circles.append((px / scale, py / scale, radius_pt))
    return AccessResult(band, circles, scale)


CLEAR_DEPTH_M = 1.5      # manoeuvring space in front of a door (accessibility standard, front approach)
LATCH_SIDE_M = 0.45      # extra width beside the door on the latch side


def door_clearances(page: PageData, zones: ZoneResult, scale: float) -> list[list[tuple[float, float]]]:
    """Wheelchair manoeuvring rectangles (as 4-point polygons in points) on both sides of every
    door on the accessible route — unit↔corridor and corridor↔stair (the album draws both sides,
    and the stair doors) — 1.5 m deep and the door's width plus the latch-side allowance wide."""
    m = pt_per_m(zones)
    space_of = _space_ids(zones)
    unit_rooms = {rid for rid, (_, k) in space_of.items() if k == UNIT}
    common = {rid for rid, (_, k) in space_of.items() if k != UNIT}
    doors = door_mask(page, scale, m)
    n, comp, stats, cents = cv2.connectedComponentsWithStats((cv2.dilate(doors, np.ones((5, 5), np.uint8)) > 0).astype(np.uint8))
    boxes = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        win = (slice(max(0, y - 2), y + h + 2), slice(max(0, x - 2), x + w + 2))
        touched = set(np.unique(zones.labels[win][comp[win] == i]).tolist()) - {0}
        ring = cv2.dilate((comp[win] == i).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        touched |= set(np.unique(zones.labels[win][ring]).tolist()) - {0}
        corridor = touched & common
        if not corridor or len(touched & (unit_rooms | common)) < 2:
            continue
        cx, cy = cents[i]
        # Corridor side: direction from the door to the corridor pixels around it.
        r = int(CLEAR_DEPTH_M * m * scale)
        ys, xs = np.nonzero(np.isin(zones.labels[max(0, int(cy) - r):int(cy) + r, max(0, int(cx) - r):int(cx) + r], list(corridor)))
        if not len(xs):
            continue
        v = np.array([xs.mean() + max(0, int(cx) - r) - cx, ys.mean() + max(0, int(cy) - r) - cy])
        if np.hypot(*v) < 1e-6:
            continue
        nrm = v / np.hypot(*v)
        tan = np.array([-nrm[1], nrm[0]])
        width = max(w, h) / scale + LATCH_SIDE_M * m        # door leaf ≈ the component's long side
        depth = CLEAR_DEPTH_M * m
        c = np.array([cx, cy]) / scale
        p0, p1 = c - tan * width / 2, c + tan * width / 2
        for side in (nrm, -nrm):  # corridor side and the room behind the door
            boxes.append([tuple(p0), tuple(p1), tuple(p1 + side * depth), tuple(p0 + side * depth)])
    return boxes
