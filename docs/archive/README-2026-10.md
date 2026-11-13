# ArchiDocGen geometry service

Reads vector architectural PDFs deterministically — CAD layers, wall/door/window geometry and
positioned room labels — so derivative sheets (occupancy, fire, accessibility) are colored from
real geometry instead of LLM-guessed coordinates. Called by `georgian-arch-gen-backend`.

Layer vocabulary: `../Layer Dictionary.md` (human-readable) → `app/layers.py` (code).

## Layout

| Path | What |
|---|---|
| `app/acadnusx.py` | Legacy Georgian CAD font text (AcadNusx/AcadMtavr Latin) ↔ Unicode Georgian |
| `app/layers.py` | Layer name → category (walls, doors, furniture, grid, …) |
| `app/extract.py` | Per page: layers, geometry in display space, decoded words; masks and renders |
| `app/zones.py` | Occupancy zones: rooms from wall geometry → units from labels + doors → zone fills |
| `app/fire.py` | Fire-rated walls: 2-hour (envelope, stair/lift cores) and 1-hour (unit/unit, unit/corridor) |
| `app/egress.py` | Longest escape-route travel distance per floor (green lines on the occupancy sheet) |
| `app/functions.py` | Room function words → №41 occupancy groups (clinics, schools, offices) |
| `app/access.py` | Accessible routes (shortest paths from the lift/stair core into every named unit room) + turning circles |
| `app/sheet.py` | Sheets drawn on the original sheet: occupancy ა-100(ა), fire ა-100(ბ), accessibility ა-100(გ); legend, title block |
| `app/main.py` | HTTP API (`GET /health`, `POST /extract`, `POST /sheets`, `POST /sheets/occupancy`) |
| `harness/answer_key.py` | Ground truth from an architect album whose derivatives are on CAD layers |
| `harness/score.py` | IoU / precision / recall / spill of a predicted coloring vs the truth |
| `harness/build.py` | Builds the answer key + baseline scores into `out/answer_key/` |
| `harness/run_zones.py` | Runs `app/zones.py` on every answer-key sheet, scores it, writes previews/diffs to `out/zones/` |
| `harness/fire_key.py` | Fire answer key (album p.39-44: red on layer `41` = 2 h, blue on the fire layer = 1 h) + line score; accessibility answer key (p.33-38 grey route fills) + area score |
| `harness/run_fire.py` | Runs `app/fire.py` on the fire answer-key sheets, scores it, writes diffs to `out/fire/` |
| `harness/run_access.py` | Runs `app/access.py` on the accessibility answer-key sheets, writes diffs to `out/access/` |
| `harness/survey.py` | Every sample PDF through the service's page checks: which pages get geometry sheets, and why the rest fall back |
| `harness/ifc_samples.py` | Test inputs from public BIM models (ifc-bench): per storey a layered PDF, a flattened PDF, a scan-like PDF and an answer key of the rooms → `Samples/Generated - …` |
| `harness/score_rooms.py` | Room-level score against those answer keys: rooms found / merged / split / labelled, per plan and input form |

## Run (Docker; no local Python packages needed)

```bash
docker build -t archidocgen-geometry:dev .

# from the ArchiDocGen project root, so tests can reach the sample PDFs
RUN='docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -w /work/georgian-arch-gen-geometry archidocgen-geometry:dev'

eval $RUN python -m pytest -q -p no:cacheprovider tests
eval $RUN python -m harness.build \
  --target "/work/Samples/Gegmebi - Sample 3/gegmebi output.pdf" \
  --source "/work/Samples/Gegmebi - Sample 3/gegmebi input.pdf"

eval $RUN python -m harness.survey
eval $RUN env RUN_SURVEY=1 python -m pytest -q -p no:cacheprovider tests/test_samples.py   # slow

eval $RUN python -m harness.run_zones \
  --source "/work/Samples/Gegmebi - Sample 3/gegmebi input.pdf"

# API on :8090
docker run --rm -p 8090:8090 archidocgen-geometry:dev
curl -F "file=@Samples/Gegmebi - Sample 3/gegmebi input.pdf" localhost:8090/extract
curl -F "file=@Samples/Gegmebi - Sample 3/gegmebi input.pdf" -F lang=ka -F kinds=occupancy,fire,accessibility localhost:8090/sheets
```

## Used by the backend

`georgian-arch-gen-backend` (`src/services/geometry/geometry.service.ts`) sends each uploaded PDF
to `POST /sheets` (occupancy, fire, accessibility) while the LLM passes run. Sheets that come back replace the
LLM-drawn sheets of that page and category (and their zoomed crops); pages listed in `skipped` (no CAD layers, no units,
zones not closed by walls) keep the LLM sheets. The backend uses `GEOMETRY_SERVICE_URL`
(default `http://localhost:8090` outside production; unset in production = feature off) and
`GEOMETRY_TIMEOUT_MS` (default 10 min). gegmebi's 7 pages (18 sheets) take about 30 s with pages processed in parallel (`GEOMETRY_WORKERS`, default min(4, CPUs)); the heaviest clinic page ~30 s before it is skipped.

## Things the real files taught us

- Coordinates must be converted to display space: gegmebi's sheets are stored rotated 270°.
- Room labels are found by **text**, not layer: `bina-01` sits on a dimension-text layer,
  `bina-02` on no layer at all.
- Layer names mislead (`kedeli` = site retaining walls, `სვლაგეზები` = toilets,
  `COLUMN` = the main concrete walls); names are hints, geometry and area checks decide.
- The architects color whole **occupancy zones** (apartment group, office suite, including
  interior walls), leave stair cores and the shared corridor uncolored, and draw green
  escape-route travel-distance lines.
- A derivative sheet can be the same drawing plotted with the view shifted (album p.28 is
  offset 17.8/10.9 pt from input p.2), so matching aligns before comparing.

## Current scores (gegmebi → architects' album p.27-32, scale 2.0)

| Sheet | Floor | Overlap (IoU) | Spill |
|---|---|---|---|
| p.27 | −3 | 0.95 | 1.8% |
| p.28 | −2 | 0.88 | 2.7% |
| p.29 | −1 | 0.89 | 1.7% |
| p.30 | 1 | 0.85 | 1.9% |
| p.31 | 2 | 0.87 | 2.2% |
| p.32 | 3 | 0.90 | 3.3% |

Reference: perfectly placed rectangles (the best today's LLM approach could do) score 0.62-0.71
with ~30% spill.

More lessons from tuning zones:
- Light-colored fills/strokes are CAD wipeouts (white masks) — not walls.
- Names can be glued to numbers ("საძინებელი27.2").
- Units grow through ordinary doors only; fire-rated doors (კ-N, NN წთ) are unit entrances.
- Units only grow into rooms with a real name, or compact pockets ≤ 4 m² — an unnamed open roof
  area is not part of an apartment. Private terraces and balconies ARE colored.
- Party walls between same-class units are filled (one continuous zone, like the architects).

## Fire sheets (gegmebi → album p.39-44, scale 2.0)

Line precision / recall within 5 pt of the architects' lines:

| Sheet | Floor | 2-hour P / R | 1-hour P / R |
|---|---|---|---|
| p.39 | −3 | 0.82 / 0.96 | — (none in album, none drawn) |
| p.40 | −2 | 0.78 / 0.87 | 0.61 / 0.78 |
| p.41 | −1 | 0.74 / 0.85 | 0.86 / 0.93 |
| p.42 | 1 | 0.47 / 0.83 | 0.93 / 0.53 |
| p.43 | 2 | 0.52 / 0.82 | 0.87 / 0.92 |
| p.44 | 3 | 0.50 / 0.77 | 0.59 / 0.52 |

Known gaps: the album doesn't mark every exterior wall (caps 2-hour precision); on the ground
floor the corridor is an open-air walkway, which the architects rate 1-hour toward the units and
we draw as 2-hour envelope. Equipment symbols (extinguishers, alarms) are not drawn yet.

Lessons:
- A stair label in the corridor, or a lift drawn with its door open, must not make the whole hall
  a 2-hour core: cores are rooms with "კიბ"/"საფეხურ", or lift/shaft rooms of shaft size.
- A balcony label inside a living room's region doesn't make the room open-air.
- Walls drawn as two outlines leave a thin free core; the envelope must bridge it.
- Lines are straightened across doorways (points off the walls are dropped).

## Accessibility sheets (gegmebi → album p.33-38, scale 2.0)

Route band precision / recall within 3 pt of the architects' grey route:

| Sheet | Floor | P / R |
|---|---|---|
| p.33 | −3 | none in album, none drawn |
| p.34 | −2 | 0.73 / 0.32 |
| p.35 | −1 | 0.80 / 0.57 |
| p.36 | 1 | 0.77 / 0.06 (open-air walkway not walkable for us) |
| p.37 | 2 | 0.81 / 0.60 |
| p.38 | 3 | 0.81 / 0.51 |

Recall is capped because the album's bands also run around beds and to the far side of rooms;
ours stop in the middle of each room. Door-clearance boxes and wheelchair symbols not drawn yet.

## Which pages get geometry sheets

`app/main.py: page_verdict` decides per page, the same for the API and the survey: the page needs
CAD layers, at least one unit, zones that stay closed by walls (≤ 40% of the sheet), and at least
75% of its named rooms inside units — otherwise it falls back to the AI and `skipped` says why.
The last rule keeps a clinic page where only a storage room matched a unit word from replacing
the AI sheet with a nearly empty one.

## Second building (harness/second_key.py)

Other offices' finished sheets carry their fire / accessibility markup on their own layers, so
stripping those layers' graphics gives the raw plan and the markup is the truth. First run
(2026-10-17, scale 1.0):

| Sample | Page check | Rated walls P / R | Route P / R |
|---|---|---|---|
| 42 Grand Master (offices) | coverage 0.65 → falls back at the 0.75 gate | 0.27 / 0.23 | none drawn |
| new/ clinic pages 2-5, 7 | most rooms not in units | — | — |

What breaks there (the N2 list): stair cores without a "კიბე" label become part of a unit, so
they're hatched, the route has no start and the core gets no 2-hour wall; this office rates the
perimeter and office/corridor walls differently; unit numbers drawn glyph by glyph ("ოფისი-#06")
are partly read; non-residential rooms (labs, cabinets, classrooms) have no unit word at all.

### N2, part 1 (2026-10-17): rules that don't depend on how one office labels things

- **Stair/lift cores from the drawing**: numbered steps (a run of 5+ consecutive numbers), or dense
  stair/lift-layer drawing (≥ 0.03 segments/pt²) in a room with no unit or room name — a duplex's
  own spiral stair stays in its apartment.
- **Doors on wall layers** (ARCHICAD): small drawings with a door-leaf-sized quarter arc (0.55-1.4 m).
  Grand Master 42 went from 0 doors to 39.
- **Scale without "1:100" text**: written room areas vs measured areas, median snapped to a
  standard scale (Grand Master 42 → 1:100; gegmebi → 1:200, same as its printed scale).
- **Corridors without a label**: big unnamed rooms with doors into 2+ units, or a unit and a core;
  rooms one unit swallowed that have doors to 2+ other units/cores are released as corridor.
- **Unit numbers drawn glyph by glyph** joined ("ოფისი-#06").

Grand Master 42 after part 1: 60% of named rooms in units (was 65% with the stair wrongly inside an
office); still held back by the 75% gate. Still open there: its corridor is split by glazed
partitions into 5-6 unnamed regions with no doors between them; office N06's upper rooms aren't
reached; the second stair is only partly found.

## Deploying (e.g. Render, Docker)

- The container listens on `$PORT` (8090 when unset).
- `GEOMETRY_TOKEN`: set a long random key; every call except `/health` must then send it in
  `x-geometry-token` (the backend does, from its own `GEOMETRY_TOKEN`). Unset = open (local only).
- `GEOMETRY_WORKERS`: pages processed in parallel. Peak memory on the 7-page gegmebi set:
  1 worker ≈ 360 MB, 2 ≈ 600 MB, 4 ≈ 1.1 GB. Use 1 on a 512 MB instance, 2 on 1–2 GB.
- Health check path: `/health`.
