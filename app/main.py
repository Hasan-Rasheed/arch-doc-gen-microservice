"""HTTP API called by the NestJS backend."""

import base64
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .extract import PageData, open_pdf, read_page, read_pdf, summary
from .sheet import access_sheet, fire_sheet, occupancy_sheet, to_jpeg
from .acadnusx import fold
from .fire import _open_air
from .functions import DWELLING, EXTRA_CLASSES, is_accessory, room_name
from .zones import ZoneResult, detect_zones

app = FastAPI(title="ArchiDocGen geometry service")

# GEOMETRY_TOKEN set (deployed): every call but /health needs the same key in x-geometry-token,
# so the public URL can't be used by anyone else. Unset (local development): open.
TOKEN = os.environ.get("GEOMETRY_TOKEN", "").strip()


@app.middleware("http")
async def require_token(request, call_next):
    if TOKEN and request.url.path != "/health":
        import hmac

        from fastapi.responses import JSONResponse

        if not hmac.compare_digest(request.headers.get("x-geometry-token", ""), TOKEN):
            return JSONResponse({"detail": "missing or wrong x-geometry-token"}, status_code=401)
    return await call_next(request)

ZONE_SCALE = 2.0
# Pages processed in parallel (one process each); GEOMETRY_WORKERS=1 turns it off.
WORKERS = int(os.environ.get("GEOMETRY_WORKERS") or min(4, os.cpu_count() or 1))
IMAGE_SCALE = 2.5
# Zones covering more than this share of the sheet mean the walls didn't close (e.g. a plan
# without wall layers) — better no sheet than a sheet painted over.
MAX_ZONE_SHARE = 0.4
# Share of the page's named rooms (circulation aside) that must fall inside a unit. A page where
# only a few rooms match a unit word (a storage room in a clinic) would otherwise replace the AI
# sheet with one that colors 2 rooms out of 50. gegmebi: 0.86-1.00; the clinic set: 0.00-0.22;
# Grand Master 42 (offices, other office): 0.65, where an unlabelled stair core was hatched as an
# office — kept out until stair cores are found from geometry, not only from "კიბე" labels.
MIN_NAMED_COVERAGE = 0.75
# Where the fire and accessibility rules are validated (else those kinds fall back to the AI; the
# occupancy sheet is still drawn):
# - fire: floors whose units are mostly labelled dwellings or offices (gegmebi; Grand Master 42
#   offices P 0.39 / R 0.49) — not zones made from room functions (clinics: no validation data);
# - accessibility: dwelling floors only (Grand Master 42's route came out nearly empty).
MIN_RESIDENTIAL_SHARE_FOR_RULES = 0.5
RULE_KINDS = {"fire", "accessibility"}
FIRE_VALIDATED_GROUPS = DWELLING | {"business"}


def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Expected a PDF file.")
    return data


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/extract")
def extract(file: UploadFile = File(...)):
    """Layers (with categories), and positioned words (Georgian decoded) for every page."""
    data = _read_upload(file)
    try:
        pages = read_pdf(data)
    except Exception as exc:  # corrupt/encrypted PDFs
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {exc}") from exc
    return {"pages": [summary(p) for p in pages]}


def page_verdict(page: PageData, zones: ZoneResult | None) -> tuple[str, dict]:
    """Whether a page gets geometry sheets ("ok") or falls back to the AI, and why. Shared by
    the API and harness/survey.py so both judge pages the same way."""
    if not page.has_layers or zones is None:
        return "no CAD layers", {}
    # Real rooms: a name and a written area ("პალატა 18.6 მ²") — title-block cells and legends
    # have names but no area.
    named = [r for r in zones.rooms.values()
             if r.has_name and r.labeled_areas and r.inside and not r.circulation]
    # Explained: in a zone, or an open balcony/terrace (it needn't join one). A support room left
    # out of every zone is a genuinely uncoloured room, so it still counts against the page.
    in_units = sum(1 for r in named if r.unit or _open_air(r))
    stats = {"units": sum(1 for v in zones.units.values() if v), "namedRooms": len(named),
             "inUnits": in_units, "coverage": round(in_units / len(named), 2) if named else 0.0}
    if not stats["units"]:
        return "no units found", stats
    covered = sum(int((m > 0).sum()) for m in zones.masks.values())
    if covered / zones.labels.size > MAX_ZONE_SHARE:
        return "zones not closed by walls", stats
    if stats["coverage"] < MIN_NAMED_COVERAGE:
        return "most rooms not in units", stats
    return "ok", stats


SHEET_KINDS = {"occupancy": occupancy_sheet, "fire": fire_sheet, "accessibility": access_sheet}


def unclassified_names(zones: ZoneResult, limit: int = 60) -> list[str]:
    """Names of real rooms (name + written area, inside the building) that no unit, function,
    support or circulation word explains — for the backend to classify (ROADMAP N2b-2)."""
    names = []
    for r in zones.rooms.values():
        if r.inside and r.has_name and r.labeled_areas and not (r.unit or r.circulation or r.core or r.function
                                                                or r.accessory or _open_air(r)):
            n = room_name(r.words)
            if n and n not in names and not is_accessory(r.words):
                names.append(n)
    return names[:limit]


def _residential_share(zones: ZoneResult) -> float:
    made = [u for u, rids in zones.units.items() if rids]
    return sum(1 for u in made if zones.unit_class[u] in DWELLING) / len(made) if made else 0.0


def _rule_kinds(zones: ZoneResult) -> set[str]:
    """Sheet kinds the rules are validated for on this page: occupancy always; fire when most
    labelled units are of a validated group; accessibility when most units are dwellings."""
    made = [u for u, rids in zones.units.items() if rids]
    labelled_validated = sum(1 for u in made if u not in zones.function_units
                             and zones.unit_class[u] in FIRE_VALIDATED_GROUPS) / len(made) if made else 0.0
    kinds = {"occupancy"}
    if labelled_validated >= MIN_RESIDENTIAL_SHARE_FOR_RULES:
        kinds.add("fire")
    if _residential_share(zones) >= MIN_RESIDENTIAL_SHARE_FOR_RULES:
        kinds.add("accessibility")
    return kinds


def _page_plan(data: bytes, index: int, room_classes: dict[str, str] | None = None) -> dict:
    """Which sheet kinds this page would get from geometry, without drawing them (the Review
    step's diagram list). Runs in a worker process like _page_sheets. A held-back page lists its
    unknown room names, like /sheets, so the backend can classify them and ask again."""
    try:
        doc = open_pdf(data)
        page = read_page(doc, index)
        zones = detect_zones(page, ZONE_SCALE, room_classes) if page.has_layers else None
        verdict, stats = page_verdict(page, zones)
    except Exception as exc:
        return {"index": index, "verdict": f"error: {exc}", "kinds": []}
    if verdict != "ok":
        entry = {"index": index, "verdict": verdict, "kinds": [], "hasLayers": page.has_layers}
        names = unclassified_names(zones) if zones is not None else []
        if names:
            entry["unclassifiedNames"] = names
        return entry
    return {"index": index, "verdict": "ok", "kinds": sorted(_rule_kinds(zones)), "hasLayers": True,
            "units": stats.get("units", 0)}


def _page_sheets(data: bytes, index: int, lang: str, kinds: list[str],
                 room_classes: dict[str, str] | None = None,
                 storeys: int | None = None, sprinklered: bool = False) -> tuple[list[dict], list[dict]]:
    """Every requested sheet kind for one page. Runs in a worker process, so it opens the PDF
    itself (PyMuPDF documents can't be shared across processes)."""
    sheets, skipped = [], []
    try:
        doc = open_pdf(data)
        page = read_page(doc, index)
        zones = detect_zones(page, ZONE_SCALE, room_classes) if page.has_layers else None  # shared by every kind
        verdict, _ = page_verdict(page, zones)
        if verdict != "ok":
            entry = {"index": index, "reason": verdict}
            # Any failed page with real rooms: the backend asks the LLM about their names and
            # retries — a building whose rooms no word list knows starts here.
            names = unclassified_names(zones) if zones is not None else []
            if names:
                entry["unclassifiedNames"] = names
            return [], [entry]
    except Exception as exc:  # one bad page must not lose the others
        return [], [{"index": index, "reason": f"error: {exc}"}]
    made = [u for u, rids in zones.units.items() if rids]
    residential = _residential_share(zones)
    allowed = _rule_kinds(zones)
    for kind in kinds:
        if kind not in allowed:
            skipped.append({"index": index, "kind": kind, "reason": "rules not validated for this building type"})
            continue
        try:
            extra = {"storeys": storeys, "sprinklered": sprinklered} if kind == "fire" else {}
            sheet = SHEET_KINDS[kind](doc, index, page, zones, ZONE_SCALE, lang, **extra)
            # Two or more units but no 1-hour wall between them or toward a corridor means the
            # corridor wasn't found (Grand Master 42); a sheet of only 2-hour lines would read as
            # "no 1-hour walls needed", so fall back instead.
            # (Sprinklered non-residential corridors need no rating, so the check is off there.)
            if kind == "fire" and len(made) >= 2 and not ({"1h", "0.5h"} & set(sheet.classes)) \
                    and (not sprinklered or residential):
                skipped.append({"index": index, "kind": kind, "reason": "no unit/corridor walls found"})
                continue
            image = base64.b64encode(to_jpeg(sheet.doc, IMAGE_SCALE)).decode()
        except Exception as exc:
            skipped.append({"index": index, "kind": kind, "reason": f"error: {exc}"})
            continue
        sheets.append({
            "index": index,
            "kind": kind,
            "sheetNumber": sheet.sheet_number,
            "derivedNumber": sheet.derived_number,
            "titleLines": sheet.title_lines,
            "classes": sheet.classes,
            "egressM": sheet.egress_m,
            "separatedDwelling": sheet.separated_dwelling,
            "units": [{"name": u.name, "class": u.cls, "areaM2": u.area_m2, "measuredM2": u.measured_m2}
                      for u in sheet.units],
            "image": f"data:image/jpeg;base64,{image}",
        })
    return sheets, skipped


def _sheets(data: bytes, lang: str, kinds: list[str], pages: list[int] | None = None,
            room_classes: dict[str, str] | None = None, storeys: int | None = None,
            sprinklered: bool = False) -> dict:
    try:
        page_count = len(open_pdf(data))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {exc}") from exc

    indices = [i for i in (pages if pages is not None else range(page_count)) if 0 <= i < page_count]
    workers = min(WORKERS, len(indices))
    if workers <= 1:
        results = [_page_sheets(data, i, lang, kinds, room_classes, storeys, sprinklered) for i in indices]
    else:
        # Pages are independent; "spawn" because forking a threaded server process is unsafe.
        with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            results = list(pool.map(_page_sheets, repeat(data), indices, repeat(lang), repeat(kinds),
                                    repeat(room_classes), repeat(storeys), repeat(sprinklered)))
    sheets = [s for page_sheets, _ in results for s in page_sheets]
    skipped = [s for _, page_skipped in results for s in page_skipped]
    return {"pageCount": page_count, "sheets": sheets, "skipped": skipped}


@app.post("/plan")
def sheet_plan(file: UploadFile = File(...), pages: str = Form(""), room_classes: str = Form("")):
    """Per page: whether geometry sheets can be drawn ("ok" or why not) and which kinds. Cheap
    compared with /sheets (no drawing), so it runs while the drawings are first read. With
    `room_classes` (the classifier's answers) and `pages`, held-back pages are checked again."""
    data = _read_upload(file)
    try:
        page_count = len(open_pdf(data))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {exc}") from exc
    page_list = [int(p) for p in pages.split(",") if p.strip().isdigit()] if pages.strip() else None
    indices = [i for i in (page_list if page_list is not None else range(page_count)) if 0 <= i < page_count]
    classes = _room_classes(room_classes)
    workers = min(WORKERS, len(indices))
    if workers <= 1:
        out = [_page_plan(data, i, classes) for i in indices]
    else:
        with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            out = list(pool.map(_page_plan, repeat(data), indices, repeat(classes)))
    return {"pageCount": page_count, "pages": out}


def _room_classes(raw: str) -> dict[str, str] | None:
    """The classifier's {room name: class} as sent by the backend: keys folded once (any spelling
    of a name matches), unknown classes dropped."""
    try:
        given = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"room_classes must be JSON: {exc}") from exc
    classes = {fold(str(k)): v for k, v in given.items() if v in EXTRA_CLASSES} if isinstance(given, dict) else {}
    return classes or None


@app.post("/sheets")
def derivative_sheets(file: UploadFile = File(...), lang: str = Form("ka"),
                      kinds: str = Form("occupancy,fire,accessibility"),
                      pages: str = Form(""), room_classes: str = Form(""), storeys: str = Form(""),
                      sprinklered: str = Form("")):
    """Derivative sheets drawn on each plan page: the original sheet with our layer (occupancy
    hatch / fire-rated walls / accessible route), a legend and the title block extended
    (ა-100 → ა-100(ა)/(ბ)/(გ)).
    Pages where zones can't be found reliably are listed in `skipped`, so the caller can fall
    back to another method for them."""
    if lang not in ("ka", "en"):
        raise HTTPException(status_code=422, detail="lang must be 'ka' or 'en'.")
    wanted = [k.strip() for k in kinds.split(",") if k.strip()]
    if not wanted or any(k not in SHEET_KINDS for k in wanted):
        raise HTTPException(status_code=422, detail=f"kinds must be a comma list of {sorted(SHEET_KINDS)}.")
    page_list = [int(p) for p in pages.split(",") if p.strip().isdigit()] if pages.strip() else None
    classes = _room_classes(room_classes)
    # Storeys the stair cores connect (basements included) — 2 h cores from four up (№41 §713.4).
    n_storeys = int(storeys) if storeys.strip().isdigit() else None
    # Sprinklered building (the project says so): Table 1018.1 / 508.4 sprinklered values.
    return _sheets(_read_upload(file), lang, wanted, page_list, classes, n_storeys,
                   sprinklered.strip().lower() in ("1", "true", "yes"))


@app.post("/sheets/occupancy")
def occupancy(file: UploadFile = File(...), lang: str = Form("ka")):
    """Occupancy sheets only (same as POST /sheets with kinds=occupancy)."""
    if lang not in ("ka", "en"):
        raise HTTPException(status_code=422, detail="lang must be 'ka' or 'en'.")
    return _sheets(_read_upload(file), lang, ["occupancy"])
