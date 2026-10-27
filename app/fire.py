"""Fire-resistance lines from the zones, the way the album's fire sheets mark them (ა-10Xc):

- 2-hour (red): the building envelope — where the enclosed floor meets outside air (open terraces
  and balconies are outside) — and every wall around a stair or lift core (№41 §713.4 / §1022.2:
  2 h when the core connects four or more storeys, 1 h otherwise — basements count).
- 1-hour (blue): walls between dwellings (§420.2 fire partitions, §708.3 ≥ 1 h), and between a
  unit and a corridor (Table 1018.1, by the unit's group and the floor's occupant load from
  Table 1004.1.2: სც > 10 occupants 1 h, or 0.5 h sprinklered; დწ any load 1 h, none
  sprinklered; other groups > 30 occupants 1 h, none sprinklered). Walls between rooms of one
  non-residential group aren't rated.
- Between units of different non-residential groups: Table 508.4 (separated occupancies), e.g.
  parking ↔ offices 2 h (1 h sprinklered); offices ↔ shops none. A dwelling toward any other use
  too: 2 h without sprinklers, 1 h with — never below the §420.2 fire partition (1 h). The album
  draws 1 h there, which is what non-separated occupancies (§508.3.3 exc. 2 → §420) allow, so
  the fire sheet notes that alternative whenever it draws such a 2 h wall.
Sprinklered values only when the project says it is sprinklered; the default is without — what
the architects' album draws (1 h corridors).

The floor inside the envelope is divided among its spaces (each unit, each corridor, each stair
core) by nearest room, so every wall is split down its middle; a wall's rating then follows from
which two spaces it separates.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

from .acadnusx import contains, folded, is_name_word
from .extract import PageData, boundary_mask, rasterize
from .layers import BOUNDARY
from .functions import DWELLING
from .zones import ZoneResult, door_mask, room_window

STAIR_WORDS = folded(("კიბ", "საფეხურ", "stair"))                 # stair, step
SHAFT_WORDS = folded(("ლიფტ", "შახტ", "lift", "elevator", "shaft"))  # lift, shaft
# A lift/shaft label only makes its room a core when the room is about shaft-sized: on gegmebi
# the lift sits inside the hall's region (its door is open in the drawing), and the whole hall
# must not become a 2-hour core because of it.
MAX_SHAFT_ROOM_PT2 = 1600  # ≈ 4 m² at 1:200
OPEN_AIR_WORDS = folded(("ტერას", "აივან", "ლოჯ", "ბალკონ", "terrace", "balcon", "loggia"))
MIN_RUN_PT = 4.0          # shorter wall pieces are corners/noise, not walls worth a line
WALL_CORE_PT = 2.5        # half the widest wall core (≈ 1 m wall at 1:200)
MIN_BUILDING_PT2 = 2000
MIN_ROOM_PT2 = 20             # smaller free bits are wall cores and drawing gaps
MAX_ENCLOSED_ROOM_PT2 = 7500  # ≈ 37 m² at 1:200 — bigger unclaimed spaces are site, not rooms
ENVELOPE_EPS_PT = 1.5
ON_WALL_PT = 2.0          # a dividing line farther than this from any wall is crossing a doorway   # ≈ 5 m² at 1:200 — smaller enclosed bits are not the building

# Space kinds in the partition.
NONE, UNIT, CORRIDOR, STAIR = 0, 1, 2, 3


@dataclass
class FireLines:
    two_hour: list[list[tuple[float, float]]]   # polylines in points (display space)
    one_hour: list[list[tuple[float, float]]]
    masks: dict[str, np.ndarray]                # "2h"/"1h"/"0.5h" -> rasterized lines at `scale`
    scale: float
    half_hour: list[list[tuple[float, float]]] = field(default_factory=list)  # sprinklered corridors
    # A dwelling ↔ other-use wall drawn 2 h by Table 508.4 (the sheet then notes the §508.3 route).
    separated_dwelling: bool = False


def _has(room, words) -> bool:
    return any(contains(t, words) for t in room.words)


def _open_air(room) -> bool:
    """Only a terrace/balcony and nothing else. A living room whose region also holds the
    balcony label (glazed door drawn as a window, so the two aren't separated) is indoors."""
    names = [t for t in room.words if is_name_word(t)]
    return bool(names) and all(contains(t, OPEN_AIR_WORDS) for t in names)


def _space_ids(zones: ZoneResult):
    """Room id -> (space id, kind). Units get one id each; corridors and stairs one id per room."""
    space_of: dict[int, tuple[int, int]] = {}
    unit_ids = {anchor: i + 1 for i, anchor in enumerate(zones.units)}
    next_id = len(unit_ids) + 1
    for rid, room in zones.rooms.items():
        if _open_air(room):
            continue
        if room.unit:
            space_of[rid] = (unit_ids[room.unit], UNIT)
        elif room.circulation or room.shared:
            core = room.core and not _has(room, SHAFT_WORDS) or _has(room, STAIR_WORDS) \
                or (_has(room, SHAFT_WORDS) and room.area_pt2 <= MAX_SHAFT_ROOM_PT2)
            kind = STAIR if core else CORRIDOR
            space_of[rid] = (next_id, kind)
            next_id += 1
    return space_of


def _envelope(zones: ZoneResult, space_of, boundary: np.ndarray, scale: float) -> np.ndarray:
    """The enclosed floor including its walls, holes filled. Built from the occupancy zones
    (which already join a unit's rooms across interior walls and door-swing pockets) plus the
    corridors and stairs, minus open-air rooms."""
    open_air = [rid for rid, r in zones.rooms.items() if _open_air(r)]
    interior = np.isin(zones.labels, list(space_of)).astype(np.uint8) * 255
    for m in zones.masks.values():
        interior |= m
    interior[np.isin(zones.labels, open_air)] = 0
    _add_enclosed_rooms(zones, space_of, set(open_air), interior, scale)
    k = max(3, int(round(10 * scale)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(interior, cv2.MORPH_CLOSE, kernel)
    # Walls drawn as two outlines leave their core as thin free space, often joined to the
    # outside; let the closing bridge it too, or the envelope gets slits along every such wall.
    free = (boundary == 0).astype(np.uint8)
    thin = cv2.distanceTransform(free, cv2.DIST_L2, 3) <= WALL_CORE_PT * scale
    closed[(closed > 0) & ~((interior > 0) | (boundary > 0) | thin)] = 0
    # Fill holes: anything not reachable from the sheet border is inside.
    h, w = closed.shape
    flood = closed.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, mask, (0, 0), 255)
    filled = closed | cv2.bitwise_not(flood)
    n, comp, stats, _ = cv2.connectedComponentsWithStats((filled > 0).astype(np.uint8))
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] / scale / scale >= MIN_BUILDING_PT2]
    return np.where(np.isin(comp, keep), 255, 0).astype(np.uint8)


def _add_enclosed_rooms(zones: ZoneResult, space_of, open_air: set[int], interior: np.ndarray,
                        scale: float) -> None:
    """Small rooms no unit claimed (a WC or kitchen the door walk didn't reach) are still inside
    the building when, across one wall, they mostly face the floor rather than the outside —
    otherwise the envelope notches around them and draws a 2-hour line through the unit."""
    reach = max(3, int(round(8 * scale)))
    k = 2 * reach + 1
    for rid, room in zones.rooms.items():
        if rid in space_of or rid in open_air or not (MIN_ROOM_PT2 <= room.area_pt2 <= MAX_ENCLOSED_ROOM_PT2):
            continue
        win = room_window(zones.labels, room, reach)
        own = zones.labels[win] == rid
        ring = (cv2.dilate(own.astype(np.uint8), np.ones((k, k), np.uint8)) > 0) & ~own
        labels = zones.labels[win][ring]
        inside = (interior[win][ring] > 0).sum()
        outside = (labels == zones.outside).sum()
        if inside > 0 and outside < 0.25 * (inside + outside):
            interior[win][own] = 255


def _partition(zones: ZoneResult, space_of, envelope: np.ndarray):
    """Space id per envelope pixel, by nearest room pixel (walls split down the middle)."""
    seed_id = np.zeros(zones.labels.shape, np.int32)
    for rid, (sid, _) in space_of.items():
        seed_id[zones.labels == rid] = sid
    src = np.where(seed_id > 0, 0, 255).astype(np.uint8)
    _, nearest = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    # nearest[] numbers the zero (seed) pixels in scan order; map that number back to its space.
    lut = np.zeros(int(nearest.max()) + 1, np.int32)
    lut[nearest[src == 0]] = seed_id[src == 0]
    part = lut[nearest]
    part[envelope == 0] = 0
    return part


# Table 508.4 (№41 = IBC 2012), hours (sprinklered, not sprinklered); None = no separation,
# "NP" = not permitted next to each other. Our classes → the table's groups.
GROUP_508 = {
    "assembly": "AE", "educational": "AE", "institutional": "I", "residential": "R", "transient": "R",
    "parking": "S2", "business": "B", "mercantile": "B", "storage": "B", "factory": "B",
}
TABLE_508_4 = {
    ("AE", "AE"): (None, None), ("AE", "I"): (1, 2), ("AE", "R"): (1, 2), ("AE", "S2"): (None, 1),
    ("AE", "B"): (1, 2),
    ("I", "I"): (None, None), ("I", "R"): (1, "NP"), ("I", "S2"): (1, 2), ("I", "B"): (1, 2),
    ("R", "R"): (None, None), ("R", "S2"): (1, 2), ("R", "B"): (1, 2),
    ("S2", "S2"): (None, None), ("S2", "B"): (1, 2),
    ("B", "B"): (None, None),
}
HOURS = {1: "1h", 2: "2h"}

# Table 1004.1.2: floor area per occupant (m², gross unless noted), for the occupant load a
# corridor serves. Mercantile uses the ground-floor value and assembly the unconcentrated one —
# the larger load when the floor isn't known.
LOAD_M2 = {
    "residential": 18.6, "transient": 18.6, "business": 9.3, "mercantile": 2.8, "assembly": 1.4,
    "educational": 1.9, "institutional": 22.3, "factory": 9.3, "storage": 46.5, "parking": 18.6,
}
# Table 1018.1: corridor walls by the group a unit belongs to — (occupants above which the
# corridor is rated, without sprinklers, with sprinklers). Where the table says "not permitted"
# without sprinklers (სც, დწ) the 1-hour wall is drawn, as the album does for dwellings.
CORRIDOR_1018 = {
    "residential": (10, "1h", "0.5h"), "transient": (10, "1h", "0.5h"),
    "institutional": (0, "1h", None),
}
CORRIDOR_OTHER = (30, "1h", None)   # თვ, სქ, სგ, სმ, სვ, სწ


def corridor_rating(group: str | None, load: float | None, sprinklered: bool) -> str | None:
    """Rating of a unit's wall toward a corridor serving `load` occupants (None: unknown → rated)."""
    above, plain, with_spr = CORRIDOR_1018.get(group or "", CORRIDOR_OTHER)
    if load is not None and load <= above:
        return None
    return with_spr if sprinklered else plain


def corridor_for_floor(groups: set[str | None], load: float | None, sprinklered: bool) -> str | None:
    """A corridor serving several groups meets the strictest of them (gegmebi −2: flats and an
    office share one corridor, rated 1 h for the flats, office side included)."""
    best = None
    for g in groups:
        r = corridor_rating(g, load, sprinklered)
        if RANK[r] > RANK[best]:
            best = r
    return best


def floor_load(zones: ZoneResult) -> float | None:
    """Occupants of the floor's units (Table 1004.1.2), or None without a drawing scale."""
    if not zones.drawing_scale:
        return None
    m2_per_pt2 = (25.4 / 72 / 1000 * zones.drawing_scale) ** 2
    load = 0.0
    for anchor, rids in zones.units.items():
        area = sum(zones.rooms[r].area_pt2 for r in rids) * m2_per_pt2
        load += area / LOAD_M2.get(zones.unit_class.get(anchor, ""), 9.3)
    return load
RANK = {"2h": 3, "1h": 2, "0.5h": 1, None: 0}


def separation_508(group_a: str | None, group_b: str | None, sprinklered: bool = False) -> str | None:
    """Table 508.4 rating between two different occupancy groups ("1h"/"2h"), or None."""
    a, b = GROUP_508.get(group_a or ""), GROUP_508.get(group_b or "")
    if not a or not b:
        return None
    hours = TABLE_508_4.get((a, b)) or TABLE_508_4.get((b, a))
    if not hours:
        return None
    h = hours[0] if sprinklered else hours[1]
    # "NP": these groups may not adjoin; the strictest rating we draw still marks the wall.
    return "2h" if h == "NP" else HOURS.get(h)


def _rating(kind_a: int, kind_b: int, group_a: str | None = None, group_b: str | None = None,
            storeys: int | None = None, sprinklered: bool = False, load: float | None = None,
            corridor: str | None = "unset") -> str | None:
    """Rating of the wall between two spaces (see the module docstring for the №41 sections)."""
    if STAIR in (kind_a, kind_b):
        return "1h" if storeys is not None and storeys < 4 else "2h"
    if kind_a == UNIT and kind_b == UNIT:
        if group_a == group_b or {group_a, group_b} <= DWELLING:
            # Dwellings from each other: fire partitions (§420.2); rooms of one other group: none.
            return "1h" if group_a in DWELLING else None
        separated = separation_508(group_a, group_b, sprinklered)
        if group_a in DWELLING or group_b in DWELLING:
            # Toward other uses: Table 508.4, but never below the §420.2 fire partition.
            return separated if RANK[separated] > RANK["1h"] else "1h"
        return separated
    if UNIT in (kind_a, kind_b) and CORRIDOR in (kind_a, kind_b):
        if corridor != "unset":
            return corridor  # the floor's corridor rating (corridor_for_floor)
        return corridor_rating(group_a if kind_a == UNIT else group_b, load, sprinklered)
    return None


def _runs(points: np.ndarray, keep: np.ndarray, scale: float, on_wall: np.ndarray | None = None,
          eps_pt: float = 0.4) -> list[list[tuple[float, float]]]:
    """Consecutive kept contour points as polylines (contours are closed: wrap around). Where a
    run leaves the walls (`on_wall` false — it is bending around a door swing), only the wall
    points on either side are kept, so the line crosses the doorway straight, like the album's."""
    if keep.all():
        runs = [np.arange(len(points)).tolist() + [0]]
    else:
        start = int(np.argmin(keep))  # begin at a gap so no run is split by the wrap
        order = np.roll(np.arange(len(points)), -start)
        runs, cur = [], []
        for i in order:
            if keep[i]:
                cur.append(i)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
    out = []
    for r in runs:
        if on_wall is not None and len(r) > 2:
            r = [i for j, i in enumerate(r) if on_wall[i] or j in (0, len(r) - 1)]
        pts = points[r].astype(np.float32)
        if len(pts) < 2 or cv2.arcLength(pts.reshape(-1, 1, 2), False) / scale < MIN_RUN_PT:
            continue
        simple = cv2.approxPolyDP(pts.reshape(-1, 1, 2), eps_pt * scale, False).reshape(-1, 2)
        out.append([(float(x) / scale, float(y) / scale) for x, y in simple])
    return out


def fire_lines(page: PageData, zones: ZoneResult, scale: float, storeys: int | None = None,
               sprinklered: bool = False) -> FireLines:
    space_of = _space_ids(zones)
    kinds = {sid: kind for sid, kind in space_of.values()}
    # Occupancy class per unit space: walls between rooms of one non-residential group aren't
    # rated (a clinic's wards and offices), walls between dwellings or different groups are.
    group = {sid: zones.unit_class.get(zones.rooms[rid].unit) for rid, (sid, kind) in space_of.items() if kind == UNIT}
    boundary = boundary_mask(page, scale)
    envelope = _envelope(zones, space_of, boundary, scale)
    part = _partition(zones, space_of, envelope)

    lines: dict[str, list] = {"2h": [], "1h": [], "0.5h": []}
    load = floor_load(zones)
    corridor = corridor_for_floor(set(group.values()), load, sprinklered) if group else None
    m = 1000 / zones.drawing_scale / 25.4 * 72 if zones.drawing_scale else None
    walls = rasterize(page, scale, (BOUNDARY - {"DOOR"}) | {"WALL_FILL"}, min_px=2)
    walls[door_mask(page, scale, m) > 0] = 0  # doors drawn on wall layers aren't wall
    wall_dist = cv2.distanceTransform((walls == 0).astype(np.uint8), cv2.DIST_L2, 3)

    # Envelope: the outer contour of the enclosed floor.
    contours, _ = cv2.findContours(envelope, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    for c in contours:
        pts = c.reshape(-1, 2)
        # Coarser simplification: the outer face has a notch at every window and column.
        lines["2h"] += _runs(pts, np.ones(len(pts), bool), scale, eps_pt=ENVELOPE_EPS_PT)

    # Interior walls: trace each space's outline and keep the stretches where the neighbor across
    # is a space of a rated pairing. Only the lower id draws a shared wall, so it's drawn once.
    h, w = part.shape
    pad = np.pad(part, 2)
    separated_dwelling = False
    for sid in np.unique(part):
        if sid == 0:
            continue
        region = (part == sid).astype(np.uint8)
        contours, _ = cv2.findContours(region, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        for c in contours:
            pts = c.reshape(-1, 2)
            ratings = np.full(len(pts), None, object)
            for i, (x, y) in enumerate(pts):
                around = pad[y:y + 5, x:x + 5]  # 5x5 window centered on (x, y)
                others = set(np.unique(around).tolist()) - {sid, 0}
                best = None
                for o in others:
                    if o < sid:
                        continue
                    r = _rating(kinds[sid], kinds[o], group.get(sid), group.get(o), storeys, sprinklered, load, corridor)
                    if r == "2h" and kinds[sid] == kinds[o] == UNIT and group.get(sid) != group.get(o) \
                            and (group.get(sid) in DWELLING or group.get(o) in DWELLING):
                        separated_dwelling = True
                    if RANK[r] > RANK[best]:
                        best = r
                ratings[i] = best
            for cls in ("2h", "1h", "0.5h"):
                keep = np.array([r == cls for r in ratings])
                if keep.any():
                    on_wall = wall_dist[pts[:, 1], pts[:, 0]] <= ON_WALL_PT * scale
                    lines[cls] += _runs(pts, keep, scale, on_wall)

    masks = {}
    for cls, polys in lines.items():
        m = np.zeros((h, w), np.uint8)
        for poly in polys:
            cv2.polylines(m, [np.round(np.array(poly) * scale).astype(np.int32)], False, 255,
                          max(1, int(round(1.2 * scale))))
        masks[cls] = m
    return FireLines(lines["2h"], lines["1h"], masks, scale, lines["0.5h"], separated_dwelling)
