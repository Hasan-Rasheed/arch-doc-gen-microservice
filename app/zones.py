"""Occupancy zones from vector geometry — the way the architects color them.

1. Rooms: the free space between boundary layers (walls, columns, doors, windows, rails) splits
   into connected regions; door leaves/arcs close doorways, so each room is its own region.
2. Labels: words whose position falls in a region become that room's text (name + area).
3. Units: an anchor label (ბინა-01 = apartment, ოფისი 1 = office) starts a unit; the unit grows
   from room to room through doors, but never through fire-rated doors (tagged კ-N / NN წთ —
   unit entrance doors) and never into stair/lift/corridor rooms. Rooms reached by two units
   are shared and stay uncolored, like the architects' corridors and stair cores.
4. Zone fill: a unit's rooms are merged into one region including the interior walls between
   them, without reaching into other units or shared rooms.
"""

import re
from collections import Counter, deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from .acadnusx import fold, folded, is_name_word, starts_with
from .functions import DWELLING, GROUPS, extra_class, function_class, is_accessory, room_name, unit_role
from .extract import PageData, boundary_mask, rasterize
from .layers import BOUNDARY

# Occupancy class per unit-anchor keyword, matched at the start of the label in any spelling
# (Georgian, AcadNusx Latin, plain Latin — see acadnusx.starts_with) plus English.
ANCHORS = {
    "ბინა": "residential",
    "ოფისი": "business",
    "საოფისე": "business",
    "მაღაზია": "mercantile",
    "კაფე": "assembly",
    "რესტორანი": "assembly",
    "სათავსო": "storage",
    "საწყობი": "storage",
    "ავტოსადგომი": "parking",
    "პარკინგი": "parking",
    "apartment": "residential",
    "apt": "residential",
    "flat": "residential",
    "office": "business",
    "shop": "mercantile",
    "store": "mercantile",
    "storage": "storage",
    "parking": "parking",
}
_ANCHOR_KEYS = [(k, fold(k)) for k in ANCHORS]
# Rooms that are never colored and that units never grow into.
CIRCULATION = folded(("კიბის", "კიბე", "ლიფტი", "დერეფანი", "კორიდორ", "ვესტიბიული", "ტამბური", "შახტა",
                       "უსაფრთხო",  # "უსაფრთხო ზონა" — area of refuge on an escape route
                       "corridor", "stair", "lift", "elevator", "lobby", "hall"))
# Fire-rated door tags: "კ-3" and "20 წთ" (minutes) next to a door.
FIRE_DOOR_TAG = re.compile(r"^(კ-\d+|წთ)$")
AREA_NUMBER = re.compile(r"^\d+[.,]\d+$|^\d+$")
# Stair/lift cores. Words: stair, stair-hall, step, lift, shaft. Drawing: VERTICAL-layer segments
# inside the room — gegmebi stairs ≈ 0.1 per pt², Grand Master 42 lifts 0.6-1.0, plain rooms < 0.01.
CORE_WORDS = folded(("კიბე", "კიბის", "საფეხურ", "ლიფტ", "შახტ", "stair", "lift", "elevator", "shaft"))
STEP_RUN = 5
MIN_CORE_SEGMENTS = 15
MIN_CORE_SEGMENT_DENSITY = 0.03
DOOR_RADIUS_M = (0.55, 1.4)   # door leaf widths, single and wide doors
UNIT_ID_PART = re.compile(r"[-–#№0-9A-Za-z]+")
SCALE_TEXT = re.compile(r"1\s*:\s*(\d{2,4})")


@dataclass
class Room:
    id: int
    area_pt2: float
    words: list[str] = field(default_factory=list)
    labeled_areas: list[float] = field(default_factory=list)  # numbers written as "NN.N მ²"
    anchor: str | None = None        # "ბინა-01", "ოფისი 1"
    anchor_class: str | None = None
    circulation: bool = False
    core: bool = False               # stair or lift core (from its label or its drawing)
    inside: bool = True              # inside the building's walls (not a title-block cell)
    function: str | None = None      # occupancy class from the room's own name (functions.py)
    strong_function: bool = False    # a function no apartment/storage unit may grow into
    accessory: bool = False          # classified as a support room by an outside classifier
    unit: str | None = None          # anchor of the unit this room belongs to
    shared: bool = False
    bbox_pt: tuple[float, float] = (0.0, 0.0)  # width, height in points
    bbox_px: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h at the detection scale

    @property
    def text(self) -> str:
        return " ".join(self.words)

    @property
    def has_name(self) -> bool:
        """A real room name (საძინებელი, wc, ...), not just grid letters, section refs (ა-300)
        or dimension numbers that happen to sit inside the region."""
        return any(is_name_word(w) for w in self.words)

    @property
    def joinable(self) -> bool:
        compact = max(self.bbox_pt) <= MAX_POCKET_SIDE_PT
        return self.has_name or (self.area_pt2 <= MAX_UNLABELED_POCKET_PT2 and compact)


@dataclass
class ZoneResult:
    labels: np.ndarray               # room id per pixel (0 = boundary/none)
    outside: int                     # room id of the space outside the building
    rooms: dict[int, Room]
    units: dict[str, list[int]]      # anchor -> room ids
    unit_class: dict[str, str]
    masks: dict[str, np.ndarray]     # occupancy class -> 0/255 zone mask
    drawing_scale: int | None        # e.g. 200 for 1:200
    area_checks: list[dict]
    function_units: set[str] = field(default_factory=set)  # units made from a room's function name
    scale: float = 2.0               # pixels per point of `labels`


def _room_at(labels: np.ndarray, x: float, y: float, scale: float, search_px: int = 6) -> int:
    """Room id under a point; labels sit on hatch/furniture sometimes, so look around a little."""
    h, w = labels.shape
    cx, cy = int(x * scale), int(y * scale)
    for r in range(0, search_px + 1, 2):
        ys, xs = slice(max(0, cy - r), min(h, cy + r + 1)), slice(max(0, cx - r), min(w, cx + r + 1))
        ids, counts = np.unique(labels[ys, xs], return_counts=True)
        keep = ids != 0
        if keep.any():
            return int(ids[keep][np.argmax(counts[keep])])
    return 0


STANDARD_SCALES = (20, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 1000)


def scale_from_areas(rooms: dict[int, Room]) -> int | None:
    """Scale from rooms whose written area ("43.9 მ²") can be compared with their measured size,
    for sheets that don't print "1:100" (Grand Master 42). Median over rooms, snapped to a standard
    scale if within 15%; None with fewer than 3 usable rooms."""
    est = []
    for r in rooms.values():
        if len(r.labeled_areas) == 1 and r.labeled_areas[0] > 1 and r.area_pt2 > 50:
            est.append((r.labeled_areas[0] / r.area_pt2) ** 0.5 / (25.4 / 72 / 1000))
    if len(est) < 3:
        return None
    median = float(np.median(est))
    best = min(STANDARD_SCALES, key=lambda s: abs(s - median) / s)
    return best if abs(best - median) / best <= 0.15 else None


def drawing_scale(page: PageData) -> int | None:
    """Scale denominator from sheet text ("1:200", or "1 : 100" drawn as three words); the most
    common value wins."""
    found = [int(m.group(1)) for w in page.words for m in [SCALE_TEXT.search(w.text)] if m]
    for w in page.words:
        if w.text.strip() != ":":
            continue
        size, cy = w.size or 4.0, w.center[1]
        near = [v for v in page.words if abs(v.center[1] - cy) < 0.5 * size]
        left = [v for v in near if 0 <= w.bbox[0] - v.bbox[2] < 1.5 * size and v.text.strip() == "1"]
        right = [v for v in near if 0 <= v.bbox[0] - w.bbox[2] < 1.5 * size and re.fullmatch(r"\d{2,4}", v.text.strip())]
        if left and right:
            found.append(int(min(right, key=lambda v: v.bbox[0]).text))
    return max(set(found), key=found.count) if found else None


def _group_room_words(page: PageData, labels: np.ndarray, scale: float, skip_layers: set[str]) -> dict[int, list]:
    by_room: dict[int, list] = {}
    for w in page.words:
        info = page.layers.get(w.layer)
        if info and info.cls.category in skip_layers:
            continue
        rid = _room_at(labels, *w.center, scale)
        if rid:
            by_room.setdefault(rid, []).append(w)
    return by_room


def _unit_id(anchor, words) -> str:
    """The unit name with its number: "ბინა-09" as is; "ოფისი" + "1" → "ოფისი 1"; and
    "ოფისი" + "-" "#" "0" "6" → "ოფისი-#06" (some fonts draw the number one glyph at a time)."""
    if re.search(r"\d", anchor.display):
        return anchor.display
    size = anchor.size or 4.0
    cy, x = anchor.center[1], anchor.bbox[2]
    line = sorted((v for v in words if v is not anchor and abs(v.center[1] - cy) < 0.4 * size
                   and v.bbox[0] >= x - 0.2), key=lambda v: v.bbox[0])
    parts = []
    for v in line:
        if v.bbox[0] - x > 0.6 * size or not UNIT_ID_PART.fullmatch(v.display):
            break
        parts.append(v.display)
        x = v.bbox[2]
    suffix = "".join(parts)
    if not re.search(r"\d", suffix):
        return anchor.display
    return anchor.display + ("" if suffix[0] in "-–#№" else " ") + suffix


MAX_CORRIDOR_WIDTH_M = 3.0
PARTITION_M = 0.5     # reach across a partition (and the wall-core sliver some draw inside it)
MIN_CONTACT_M = 0.6   # a corridor piece faces the corridor along at least this much


def _extend_corridors(labels: np.ndarray, rooms: dict[int, Room], scale: float, pt_per_m: float | None) -> None:
    """Corridors split by glazed partitions (no doors between the pieces, Grand Master 42): a
    narrow unclaimed region — shorter side ≤ 3 m, corridor-sized rather than office-sized — that
    faces a corridor across a partition along ≥ 0.6 m is corridor too (a corridor continuing
    through a screen shares its whole width; a closet behind a wall doesn't). Repeats until
    nothing changes, so a chain of pieces joins up."""
    if not pt_per_m:
        return
    reach = max(3, int(round(PARTITION_M * pt_per_m * scale)))
    k = 2 * reach + 1
    min_contact = MIN_CONTACT_M * pt_per_m * scale * reach  # ≈ boundary length × band width (px²)
    changed = True
    while changed:
        changed = False
        corridors = [rid for rid, r in rooms.items() if r.circulation and not r.core]
        for rid, room in rooms.items():
            if room.unit or room.anchor or room.core or room.circulation or room.function or not room.inside:
                continue
            width_m = min(room.bbox_pt) / pt_per_m
            # Tiny bits are skipped, except slivers: the wall-core strip some offices draw inside a
            # partition is what connects two corridor pieces.
            if width_m > MAX_CORRIDOR_WIDTH_M or (room.area_pt2 <= MAX_UNLABELED_POCKET_PT2 / 4 and width_m > 0.5):
                continue
            win = room_window(labels, room, reach)
            own = labels[win] == rid
            ring = (cv2.dilate(own.astype(np.uint8), np.ones((k, k), np.uint8)) > 0) & ~own
            if np.isin(labels[win][ring], corridors).sum() >= min_contact:
                room.circulation = True
                changed = True


def _release_corridors(rooms: dict[int, Room], units: dict[str, list[int]], links: list[set[int]]) -> None:
    """A room one unit grew into, but which has doors to two or more *other* units or cores, is
    the corridor between them: units enter it through fire-rated doors the walk doesn't cross, so
    the one office with an ordinary door to it would otherwise swallow it (Grand Master 42)."""
    touching: dict[int, set] = {}
    for touched in links:
        for a in touched:
            if a in rooms:
                touching.setdefault(a, set()).update(b for b in touched if b != a and b in rooms)
    for rid, room in rooms.items():
        if not room.unit or room.anchor:
            continue
        others = {rooms[n].unit for n in touching.get(rid, ()) if rooms[n].unit and rooms[n].unit != room.unit}
        others |= {"core"} if any(rooms[n].core for n in touching.get(rid, ())) else set()
        if len(others) >= 2:
            units[room.unit].remove(rid)
            room.unit, room.circulation = None, True


def _mark_unlabelled_corridors(rooms: dict[int, Room], links: list[set[int]]) -> None:
    """A big unnamed room with doors into two or more units, or into a unit and a stair/lift
    core, is a corridor even when nobody wrote "დერეფანი" in it (Grand Master 42, gegmebi's
    ground-floor walkway). All doors count — units open onto corridors through fire-rated doors."""
    graph: dict[int, set[int]] = {}
    for touched in links:
        for a in touched:
            graph.setdefault(a, set()).update(b for b in touched if b != a)
    for rid, room in rooms.items():
        # Annotation text often sits in a corridor, so a "name" there doesn't rule it out.
        if room.unit or room.anchor or room.core or room.circulation \
                or room.area_pt2 <= MAX_UNLABELED_POCKET_PT2:
            continue
        nbs = [rooms[n] for n in graph.get(rid, ()) if n in rooms]
        units = {n.unit for n in nbs if n.unit}
        if len(units) >= 2 or (units and any(n.core for n in nbs)):
            room.circulation = True


def _has_step_numbers(tokens: list[str], run: int = STEP_RUN) -> bool:
    """Stairs number their steps: a run of consecutive integers (1 2 3 4 5, or 6 … 11)."""
    nums = sorted({int(t) for t in tokens if re.fullmatch(r"[0-9]{1,2}", t)})  # not "²": isdigit() is True
    best = cur = 1 if nums else 0
    for a, b in zip(nums, nums[1:]):
        cur = cur + 1 if b == a + 1 else 1
        best = max(best, cur)
    return best >= run


def _mark_cores(page: PageData, labels: np.ndarray, rooms: dict[int, Room], scale: float) -> None:
    """Stair and lift cores, also when nobody labelled them "კიბე": rooms with numbered steps, or
    dense stair/lift-layer drawing (treads, lift car). A room with a unit or room name is never a
    core — a duplex's own spiral stair belongs to the apartment."""
    segs: Counter = Counter()
    h, w = labels.shape
    for d in page.drawings:
        info = page.layers.get((d.get("layer") or "").strip())
        if not info or info.cls.category != "VERTICAL":
            continue
        for it in d["items"]:
            if it[0] == "l":
                x, y = int((it[1].x + it[2].x) / 2 * scale), int((it[1].y + it[2].y) / 2 * scale)
                if 0 <= x < w and 0 <= y < h:
                    segs[int(labels[y, x])] += 1
    for rid, room in rooms.items():
        if room.anchor:
            continue
        labelled = any(starts_with(t, CORE_WORDS) for t in room.words)
        drawn = not room.has_name and segs[rid] >= MIN_CORE_SEGMENTS \
            and segs[rid] / max(room.area_pt2, 1.0) >= MIN_CORE_SEGMENT_DENSITY
        if labelled or _has_step_numbers(room.words) or drawn:
            room.core = True
            room.circulation = True


def _tokens(words) -> list[str]:
    """Room text as tokens. Some sheets glue a name to its area ("საძინებელი27.2"), so split
    Georgian letters from a directly following number."""
    out = []
    for w in words:
        out.extend(t for t in re.split(r"(?<=[ა-ჰ])(?=\d)", w.display) if t)
    return out


AREA_UNITS = {"მ", "კვ.მ.", "კვ.მ", "მ2", "მ²", "m", "m2", "m²", "㎡", "sqm", "sq.m.", "sq.m", "kv.m.", "kv.m"}
GLUED_AREA = re.compile(r"^(\d+[.,]?\d*)(მ2|მ²|m2|m²|㎡|კვ\.მ\.?)$")


def _parse_areas(tokens: list[str]) -> list[float]:
    """Numbers followed by an area unit ("27.2 მ²", "27.54 m²", "27.2 კვ.მ.") or glued to it
    ("27.2მ²"). On some sheets the ² is a separate "2" word after "მ"."""
    out = []
    for a, b in zip(tokens, tokens[1:]):
        if AREA_NUMBER.match(a) and b in AREA_UNITS:
            out.append(float(a.replace(",", ".")))
    for t in tokens:
        if m := GLUED_AREA.match(t):
            out.append(float(m.group(1).replace(",", ".")))
    return out


def _drawn_doors(page: PageData, pt_per_m: float | None) -> PageData:
    """Doors drawn on wall layers (ARCHICAD exports, Grand Master 42): a small drawing on a
    boundary layer holding a door-leaf-sized quarter arc (the swing). The whole drawing must be
    door-sized too, so a wall outline that happens to include an arc isn't taken for a door."""
    lo, hi = (DOOR_RADIUS_M[0] * pt_per_m, DOOR_RADIUS_M[1] * pt_per_m) if pt_per_m else (8.0, 40.0)
    keep = []
    for d in page.drawings:
        info = page.layers.get((d.get("layer") or "").strip())
        if not info or info.cls.category not in BOUNDARY or info.cls.category == "DOOR":
            continue
        r = d["rect"]
        if max(r.width, r.height) > 1.6 * hi:
            continue
        for it in d["items"]:
            if it[0] != "c":
                continue
            xs, ys = [q.x for q in it[1:5]], [q.y for q in it[1:5]]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            if lo <= max(w, h) <= hi and min(w, h) > 0.6 * max(w, h):
                keep.append(d)
                break
    return PageData(page.index, page.width, page.height, page.rotation, page.has_layers,
                    page.layers, [], keep)


def door_mask(page: PageData, scale: float, pt_per_m: float | None) -> np.ndarray:
    """Doors from the door layer plus doors drawn on wall layers."""
    return rasterize(page, scale, {"DOOR"}, min_px=2) | rasterize(_drawn_doors(page, pt_per_m), scale, min_px=2)


def _door_adjacency(page: PageData, labels: np.ndarray, scale: float,
                    pt_per_m: float | None = None) -> tuple[list[set[int]], list[bool]]:
    """For each door: which rooms it connects, and whether it carries a fire-rating tag."""
    doors = door_mask(page, scale, pt_per_m)
    if not doors.any():
        return [], []
    grown = cv2.dilate(doors, np.ones((7, 7), np.uint8))
    n, comp, stats, _ = cv2.connectedComponentsWithStats((grown > 0).astype(np.uint8))
    tags = [w for w in page.words if FIRE_DOOR_TAG.match(w.display)]
    near = int(14 * scale)  # tags sit within ~14 pt of their door
    links, fire = [], []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        ring = cv2.dilate((comp[y:y + h, x:x + w] == i).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        touched = set(np.unique(labels[y:y + h, x:x + w][ring]).tolist()) - {0}
        links.append(touched)
        fire.append(any(x - near <= t.center[0] * scale <= x + w + near and
                        y - near <= t.center[1] * scale <= y + h + near for t in tags))
    return links, fire


def detect_zones(page: PageData, scale: float = 2.0, room_classes: dict[str, str] | None = None) -> ZoneResult:
    """room_classes: optional {folded room name: class} from an outside classifier (the backend
    asks an LLM about names functions.py doesn't know): a group, "accessory" or "circulation"."""
    boundary = boundary_mask(page, scale)
    n, labels, stats, _ = cv2.connectedComponentsWithStats((boundary == 0).astype(np.uint8), connectivity=4)
    outside = int(np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1) if n > 1 else 0

    rooms = {i: Room(i, stats[i, cv2.CC_STAT_AREA] / scale / scale,
                     bbox_pt=(stats[i, cv2.CC_STAT_WIDTH] / scale, stats[i, cv2.CC_STAT_HEIGHT] / scale),
                     bbox_px=tuple(int(v) for v in stats[i, :4]))
             for i in range(1, n) if i != outside}
    # Not DIMENSION: room labels like ბინა-01 are often typed on a dimension-text layer.
    skip = {"GRID", "SHEET"}
    for rid, words in _group_room_words(page, labels, scale, skip).items():
        if rid not in rooms:
            continue
        room = rooms[rid]
        room.words = _tokens(words)
        room.labeled_areas = _parse_areas(room.words)
        for w in words:
            key = next((k for k, f in _ANCHOR_KEYS if fold(w.display).startswith(f)), None)
            if key and room.anchor is None:
                room.anchor = _unit_id(w, words)
                room.anchor_class = ANCHORS[key]
        if room.anchor is None:
            # A unit by the classifier's word, whatever the office calls it (hotel room, "N1", …).
            role = unit_role(extra_class(room.words, room_classes))
            if role:
                room.anchor = room_name(room.words)
                room.anchor_class = role
        room.circulation = room.anchor is None and any(starts_with(t, CIRCULATION) for t in room.words)
        if room.anchor is None and extra_class(room.words, room_classes) == "circulation":
            room.circulation = True

    _mark_inside(rooms, boundary)
    for room in rooms.values():
        if room.inside and not room.anchor and not room.circulation:
            strong = function_class(room.words, strong_only=True)
            given = extra_class(room.words, room_classes)
            room.accessory = given == "accessory"
            room.function = strong or function_class(room.words) or (given if given in GROUPS else None)
            room.strong_function = strong is not None

    _mark_cores(page, labels, rooms, scale)

    # The same unnumbered name in several rooms ("ოფისი", "ოფისი") means several units, not one.
    plain = Counter(r.anchor for r in rooms.values() if r.anchor and not re.search(r"\d", r.anchor))
    seen: Counter = Counter()
    for room in rooms.values():
        if room.anchor and plain[room.anchor] > 1:
            seen[room.anchor] += 1
            room.anchor = f"{room.anchor} ({seen[room.anchor]})"

    # The scale (needed in metres for door sizes) from sheet text, else from written room areas.
    denom = drawing_scale(page) or scale_from_areas(rooms)
    pt_per_m = 1000 / denom / 25.4 * 72 if denom else None

    # Grow units through ordinary doors.
    links, fire = _door_adjacency(page, labels, scale, pt_per_m)
    graph: dict[int, set[int]] = {rid: set() for rid in rooms}
    for touched, is_fire in zip(links, fire):
        if is_fire:
            continue
        ts = [t for t in touched if t in rooms]
        for a in ts:
            graph[a].update(t for t in ts if t != a)

    reached: dict[int, set[str]] = {rid: set() for rid in rooms}
    unit_class: dict[str, str] = {}
    for rid, room in rooms.items():
        if not room.anchor:
            continue
        unit_class[room.anchor] = room.anchor_class
        seen, queue = {rid}, deque([rid])
        while queue:
            cur = queue.popleft()
            reached[cur].add(room.anchor)
            for nb in graph[cur]:
                other = rooms[nb]
                if nb in seen or other.circulation or not other.joinable or other.strong_function \
                        or (other.anchor and other.anchor != room.anchor):
                    continue
                seen.add(nb)
                queue.append(nb)

    units: dict[str, list[int]] = {a: [] for a in unit_class}
    for rid, anchors in reached.items():
        if len(anchors) == 1:
            rooms[rid].unit = next(iter(anchors))
            units[rooms[rid].unit].append(rid)
        elif len(anchors) > 1:
            rooms[rid].shared = True

    _release_corridors(rooms, units, links)
    _mark_unlabelled_corridors(rooms, links)
    _extend_corridors(labels, rooms, scale, pt_per_m)
    function_units = _function_units(rooms, units, unit_class)
    _attach_leftovers(labels, rooms, units, scale, unit_class)
    masks = _zone_masks(labels, rooms, units, unit_class, boundary, scale)

    checks = []
    if denom:
        m2_per_pt2 = (25.4 / 72 / 1000 * denom) ** 2
        for room in rooms.values():
            if len(room.labeled_areas) == 1 and not room.anchor:
                measured = room.area_pt2 * m2_per_pt2
                checks.append({"room": room.text[:40], "labeled": room.labeled_areas[0],
                               "measured": round(measured, 1),
                               "ratio": round(measured / room.labeled_areas[0], 2) if room.labeled_areas[0] else None})

    return ZoneResult(labels, outside, rooms, units, unit_class, masks, denom, checks, function_units, scale)


MAX_UNLABELED_POCKET_PT2 = 1600  # ≈ 4 m² at 1:200: door-swing pockets, small shafts
MAX_POCKET_SIDE_PT = 40           # ≈ 2.8 m at 1:200 — long thin gaps inside double walls aren't pockets


def room_window(labels: np.ndarray, room: Room, pad_px: int) -> tuple[slice, slice]:
    """The room's bounding box grown by pad_px, clipped to the image. Scanning the whole page
    per room instead made clinic plans (1,000-4,000 regions) take minutes."""
    x, y, w, h = room.bbox_px
    return (slice(max(0, y - pad_px), min(labels.shape[0], y + h + pad_px)),
            slice(max(0, x - pad_px), min(labels.shape[1], x + w + pad_px)))


def _neighbors(labels: np.ndarray, room: Room, reach_px: int) -> set[int]:
    rid = room.id
    ys, xs = room_window(labels, room, reach_px)
    crop = labels[ys, xs]
    k = 2 * reach_px + 1
    grown = cv2.dilate((crop == rid).astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    return set(np.unique(crop[grown]).tolist()) - {0, rid}


def _mark_inside(rooms: dict[int, Room], boundary: np.ndarray) -> None:
    """Rooms whose centre lies within the extent of the building's walls; the rest are sheet
    furniture (title-block and legend cells) and never become zones."""
    ys, xs = np.nonzero(boundary)
    if not len(xs):
        return
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    for room in rooms.values():
        x, y, w, h = room.bbox_px
        cx, cy = x + w / 2, y + h / 2
        room.inside = bool(x0 <= cx <= x1 and y0 <= cy <= y1)


def _function_units(rooms: dict[int, Room], units: dict[str, list[int]], unit_class: dict[str, str]) -> set[str]:
    """Rooms no unit claimed that are a function by name (ward, lab, lecture hall…) become zones
    of their own, numbered per name ("პალატა 1", "პალატა 2"). Same-class neighbours later merge
    into one continuous zone in _zone_masks, like the architects' hatch."""
    counts: Counter = Counter()
    made: set[str] = set()
    for rid, room in rooms.items():
        if room.unit or room.shared or room.core or room.circulation or not room.function:
            continue
        name = next((w.rstrip(",.") for w in room.words if is_name_word(w)), room.function)
        counts[name] += 1
        anchor = f"{name} {counts[name]}"
        room.unit = anchor
        units[anchor] = [rid]
        unit_class[anchor] = room.function
        made.add(anchor)
    return made


def _attach_leftovers(labels, rooms: dict[int, Room], units: dict[str, list[int]], scale: float,
                      unit_class: dict[str, str] | None = None) -> None:
    """Rooms the door walk couldn't reach but that clearly belong to one unit: labeled
    non-circulation rooms (balconies behind glazed doors drawn on the window layer) and tiny
    unlabeled pockets (inside door swings). Attached only when they border exactly one unit
    and no stair/corridor — except support rooms (WC, auxiliary) amid rooms of one
    non-residential group, which take that group even off a corridor (clinics)."""
    reach = max(3, int(round(8 * scale)))  # across one wall
    for rid, room in rooms.items():
        if room.unit or room.shared or room.circulation or room.anchor:
            continue
        if not room.joinable:
            continue
        nbs = _neighbors(labels, room, reach)
        near_units = {rooms[n].unit for n in nbs if n in rooms and rooms[n].unit}
        classes = {unit_class[u] for u in near_units} if unit_class else set()
        shared_group = (len(classes) == 1 and not classes & DWELLING
                        and (is_accessory(room.words) or room.accessory))
        if any(rooms[n].circulation for n in nbs if n in rooms) and not shared_group:
            continue
        # An unlabeled pocket that also opens onto a bigger space outside every unit (a lobby or
        # hall not marked as corridor) is the door swing on the outer side: it stays outside, or
        # the unit's outline bulges round the door.
        if not room.words and any(n in rooms and rooms[n].unit is None and not rooms[n].circulation
                                  and rooms[n].area_pt2 > 3 * room.area_pt2 for n in nbs):
            continue
        if len(near_units) == 1 or shared_group:
            room.unit = min(near_units)
            units[room.unit].append(rid)


def _zone_masks(labels, rooms, units, unit_class, boundary, scale) -> dict[str, np.ndarray]:
    """One region per unit: its rooms plus the interior walls between them."""
    wall_px = max(3, int(round(10 * scale)) | 1)  # interior walls are up to ~0.4 m ≈ 6 pt at 1:200
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (wall_px, wall_px))
    others_all = np.isin(labels, [rid for rid, r in rooms.items() if r.unit is None])
    masks: dict[str, np.ndarray] = {}
    for anchor, rids in units.items():
        if not rids:
            continue
        unit = np.isin(labels, rids).astype(np.uint8) * 255
        closed = cv2.morphologyEx(unit, cv2.MORPH_CLOSE, kernel)
        # Only fill wall pixels (plus the unit itself): never paint other rooms or outside.
        closed[(closed > 0) & ~((unit > 0) | (boundary > 0))] = 0
        closed[others_all] = 0
        for other_anchor, other_rids in units.items():
            if other_anchor != anchor and other_rids:
                closed[np.isin(labels, other_rids)] = 0
        cls = unit_class[anchor]
        masks[cls] = np.maximum(masks.get(cls, np.zeros_like(unit)), closed)

    # Party walls between neighboring units of the same class are filled too (the architects
    # hatch one continuous residential zone) — walls only, never shared rooms or other classes.
    for cls, m in masks.items():
        merged = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel)
        add = (merged > 0) & (m == 0) & (boundary > 0) & ~others_all
        for other_cls, om in masks.items():
            if other_cls != cls:
                add &= om == 0
        m[add] = 255
    return masks
