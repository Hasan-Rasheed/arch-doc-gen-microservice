"""Classify CAD layer names into pipeline categories.

Human-readable source of truth: `Layer Dictionary.md` at the project root. A name is only a
hint — callers must still confirm boundary layers with geometry/area checks, because real
files mislabel layers (in gegmebi, `kedeli` = site retaining walls, `სვლაგეზები` = toilets).
"""

import re
from dataclasses import dataclass

from .acadnusx import fold

# Categories that stop the room flood-fill.
BOUNDARY = {"WALL", "COLUMN", "FINISH_EXT", "DOOR", "WINDOW", "RAILING"}

# Exact (normalized) names verified by rendering real files. Highest confidence; wins over tokens.
VERIFIED = {
    "column": "COLUMN",            # gegmebi: main RC walls, whole building outline
    "column-h": "WALL_FILL",
    "kedeli": "SITE",               # gegmebi: site retaining walls, not room walls
    "dablokili": "WALL",
    "სვლაგეზები": "SANITARY",       # "escape routes" in name, toilets in content
    "duravit": "SANITARY",
    "0 sankvandzi": "SANITARY",
    "hatch-art": "SITE",            # ground hatch around the building
    "5.h-vijat ne dukje": "OVERHEAD_HIDDEN",  # Albanian: "hidden lines"
    "kibe": "SITE",                 # site stairs
    "karis cecxlmedegoba": "ANNOTATION",      # door fire-rating tags (fire-plan input)
    "z01_nakveti": "SITE",
    "height": "ANNOTATION",
    "defpoint": "SHEET",
    "defpoints": "SHEET",
    # ARCHICAD template names (seen in 12-16 sample files from several offices).
    "structural - bearing": "WALL",       # load-bearing walls and columns
    "structural - combined": "WALL",
    "structural - non-bearing": "WALL",
    # Fire layers named after rulebook №41 (the album's 2-hour lines are on layer "41").
    "41": "DERIVATIVE_FIRE",
    "000-41": "DERIVATIVE_FIRE",
    "cont-mjr": "SITE",                   # major terrain contours
    "cont-mnr": "SITE",
    "0": "UNKNOWN",
    ".": "UNKNOWN",
    "_": "UNKNOWN",
    "": "UNKNOWN",
}

# Modifier tokens: applied after the base category is known.
_HATCH = {"h", "hatch", "patt", "pattern", "ptrn", "strixi", "shtrikhovka", "Strixi"}
_TEXT = {"txt", "text", "teqsti", "tekst"}
_TAG = {"iden", "tag", "num", "nomeri"}
_SYMBOL = {"symbol", "symb", "sym"}
_DIM = {"dim", "dims"}
_DEMO = {"demo", "dem"}

# Base vocabulary. Keys are fold()-ed at import, so Georgian / AcadNusx / informal Latin /
# any case all match. Order matters: earlier categories win when a name has tokens from several.
_VOCAB: list[tuple[str, list[str]]] = [
    ("DERIVATIVE_OCCUPANCY", ["dakavebuloba", "dakavebulobis", "დაკავებულობა", "დაკავებულობ", "occupancy",
                              "occup"]),
    # "საათი"/"სთ" (hours): fire-resistance lines, e.g. "!კედლის საათები - 2 საათი - ლაინებში" —
    # listed before WALL so a "wall hours" layer can never become a room boundary.
    ("DERIVATIVE_FIRE", ["saxandzro", "სახანძრო", "cecxlmedegoba", "ცეცხლმედეგობა", "fireresistance",
                         "fire", "evakuacia", "ევაკუაცია", "egress", "evac", "exit", "gasasvleli",
                         "საათი", "საათები", "saati", "saatebi", "ხანძარმედეგობა"]),
    ("DERIVATIVE_ACCESS", ["misawvdomoba", "misacvdomobis", "misawvdomobis", "მისაწვდომობა", "accessibility", "access"]),
    ("SHEET", ["title", "ttlb", "border", "frame-sheet", "sheet", "legend", "viewport", "vport", "xref",
               "pirobiti", "პირობითი", "ramka", "рамка", "shtamp", "штамп", "gen-title"]),
    ("GRID", ["grid", "axis", "axes", "rerZi", "ღერძი", "gherdzi", "osi", "оси"]),
    ("DIMENSION", ["dim", "dims", "dimension", "dimensioning", "zoma", "ზომა", "zomebi", "razmery", "размеры"]),
    ("SITE", ["topo", "contour", "site", "plot", "property", "prop", "tree", "trees", "plant", "plnt", "landscape",
              "vegetation", "nakveti", "ნაკვეთი", "shenoba", "შენობა", "ferdobi", "ფერდობი", "reliefi", "relef",
              "xeebi", "ხეები", "gamwvaneba", "betoni", "bordiuri", "gobe", "uchastok", "участок", "zdanie"]),
    ("OVERHEAD_HIDDEN", ["beam", "overhead", "above", "hidden", "ovhd", "hddn"]),
    ("MEP", ["mep", "riser", "hvac", "plumb", "elec", "sewer", "gas", "gazi", "kanalizacia", "კანალიზაცია",
             "kavshirgabmuloba"]),
    ("SANITARY", ["sanitary", "wc", "toilet", "fixt", "bath", "santeqnika", "სანტექნიკა", "sankvandzi", "santekhnika"]),
    ("FURNITURE", ["furniture", "furn", "furnit", "kitchen", "light", "lighting", "aveji", "ავეჯი", "mebel", "мебель"]),
    ("VERTICAL", ["stair", "stairs", "str", "strs", "lift", "elev", "elevator", "evtr", "shaft", "kibe", "კიბე",
                  "lifti", "ლიფტი", "shaxta", "Saxta", "შახტა", "lestnica", "лестница", "лифт", "shakhta"]),
    ("RAILING", ["handrail", "railing", "rail", "hral", "balustrade", "parapet", "moajiri", "მოაჯირი",
                 "perila", "ograzhdenie"]),
    ("DOOR", ["door", "doors", "dr", "kari", "კარი", "karebi", "dver", "dveri", "дверь"]),
    ("WINDOW", ["window", "wind", "win", "glaz", "glazing", "curtain", "fanjara", "ფანჯარა", "vitraji",
                "vitraJi", "ვიტრაჟი", "okno", "okna", "окно", "vitrazh", "fanjrebi", "ფანჯრები", "vitrajebi"]),
    ("FINISH_EXT", ["finish"]),
    ("COLUMN", ["column", "col", "cols", "pillar", "sveti", "სვეტი", "kolona", "კოლონა", "rkb", "monoliti",
                "kolonna", "колонна", "pilon", "monolit", "svetebi", "სვეტები", "kolonebi", "კოლონები"]),
    ("WALL", ["wall", "walls", "partition", "prht", "block", "brick", "masonry", "kedeli", "კედელი", "tixari",
              "ტიხარი", "kedlebi", "კედლები", "tixrebi", "ტიხრები", "bloki", "aguri", "stena", "стена", "peregorodka", "перегородка", "kladka"]),
    ("ROOM_TEXT", ["room", "rooms", "area", "areas", "zone", "space", "farti", "fartobi", "fartebi", "ფართი",
                   "otaxi", "ოთახი", "zona", "pomeshcheniya", "ploshchadi"]),
    ("FLOOR_PATTERN", ["tile", "paving", "patt"]),
    ("ANNOTATION", ["anno", "note", "symbol", "symb", "section", "elevation", "sign", "tag", "height", "level",
                    "detail", "detali", "detalebi", "enlarged", "equip", "otmetki"]),
]
_VOCAB_FOLDED = [(cat, {fold(w) for w in words}) for cat, words in _VOCAB]


@dataclass(frozen=True)
class LayerClass:
    category: str
    confidence: str  # "verified" | "high" | "medium" | "none"
    reason: str


def normalize(name: str) -> str:
    """`WALL-INT   (NEO-A)` -> `wall-int`; `Axis-Art` -> `axis`; `X_Pen_No__6` -> `x`."""
    n = name.strip()
    n = re.sub(r"\s*\([^)]*\)\s*$", "", n)          # office suffix "(NEO-A)"
    n = re.sub(r"_Pen_No__\d+$", "", n)              # ARCHICAD DWG export
    n = re.sub(r"^New_", "", n)                      # ARCHICAD DWG export, newer versions
    n = re.sub(r"-Art$", "", n)
    n = n.strip(" -_")
    return re.sub(r"\s+", " ", n).lower()


def tokens(normalized: str) -> list[str]:
    return [fold(t) for t in re.split(r"[-_ .]+", normalized) if t]


def classify(name: str) -> LayerClass:
    norm = normalize(name)
    if norm in VERIFIED:
        return LayerClass(VERIFIED[norm], "verified", f"verified name '{norm}'")

    toks = tokens(norm)
    # Floor text / area text is a label source even though "floor" alone means nothing.
    base_cat, base_tok, exact = None, None, False
    for cat, words in _VOCAB_FOLDED:
        hit = next((t for t in toks if t in words), None)
        if hit is None:
            hit = next((t for t in toks for w in words if len(w) >= 4 and w in t), None)
            if hit is not None and base_cat is None:
                base_cat, base_tok, exact = cat, hit, False
            continue
        base_cat, base_tok, exact = cat, hit, True
        break

    mods = set(toks) - {base_tok}
    folded_hatch = {fold(m) for m in _HATCH}
    if mods & folded_hatch:
        if base_cat in {"WALL", "COLUMN", "FINISH_EXT"}:
            return LayerClass("WALL_FILL", "high", f"hatch of {base_cat.lower()}")
        if base_cat is None and "floor" in toks:
            return LayerClass("FLOOR_PATTERN", "high", "floor hatch")
        if base_cat in {"SITE", None}:
            return LayerClass("SITE" if base_cat else "UNKNOWN", "medium", "hatch layer")
    if mods & _DEMO:
        return LayerClass("OVERHEAD_HIDDEN", "high", "demolition layer")
    if mods & _TEXT:
        if base_cat in {"ROOM_TEXT", None} and ("floor" in toks or base_cat == "ROOM_TEXT"):
            return LayerClass("ROOM_TEXT", "high", "floor/room text")
        if base_cat not in {"DIMENSION", "SHEET"}:
            return LayerClass("ANNOTATION", "high", f"text of {base_cat or 'unknown'}")
    if mods & (_TAG | _SYMBOL) and base_cat not in {"VERTICAL", "DIMENSION", "SHEET", "ROOM_TEXT", None}:
        return LayerClass("ANNOTATION", "high", f"tags/symbols of {base_cat.lower()}")
    if mods & _DIM:
        return LayerClass("DIMENSION", "high", "dimension modifier")

    if base_cat is None:
        if "floor" in toks:
            return LayerClass("FLOOR_PATTERN", "medium", "floor layer without known modifier")
        return LayerClass("UNKNOWN", "none", "no dictionary match")
    return LayerClass(base_cat, "high" if exact else "medium", f"token '{base_tok}'")
