# Spec: HTTP API

The service the backend calls to read CAD PDFs and draw the colour sheets. It is FastAPI, run
with uvicorn.

## Rules (current truth)

- **`GET /health`:** always open; used by the host's health check.
- **`POST /extract`** (`file`): a per-page summary of layers, geometry and words. Used for
  debugging.
- **`POST /plan`** (`file`, `pages?`, `room_classes?`):
  - per page, whether geometry sheets can be drawn (`verdict: "ok"` or the reason not) and which
    kinds;
  - **nothing is drawn**, so it is cheap; the backend calls it during the Read step;
  - a held-back page lists `unclassifiedNames` for the backend's LLM classifier, and is checked
    again when `room_classes` and `pages` are sent.
- **`POST /sheets`** (`file`, `lang` ka|en, `kinds`, `pages?`, `room_classes?`, `storeys?`,
  `sprinklered?`):
  - draws the occupancy, fire and accessibility sheets on each plan page;
  - pages that can't be done reliably are listed in `skipped` with the reason, and the backend
    falls back to AI sheets for them;
  - `storeys` is the number of storeys the stair cores connect (2 h cores from 4);
  - `sprinklered` applies the sprinklered values of Tables 1018.1 and 508.4.
- **`POST /sheets/occupancy`:** the same as `/sheets` with `kinds=occupancy`.
- **`room_classes`** is the classifier's `{room name: class}`:
  - names are folded, so any spelling matches;
  - unknown classes are dropped;
  - the classes are those in `EXTRA_CLASSES`: the №41 groups, `unit:<group>`, `accessory` and
    `circulation`.
- **Token:** when `GEOMETRY_TOKEN` is set, every call except `/health` must send it in
  `x-geometry-token`. If it is unset, the API is open (local only).
- **Parallel pages:** pages are processed in a process pool (`GEOMETRY_WORKERS`, default
  min(4, CPUs)). gegmebi (7 pages, 18 sheets) takes about 30 s.

## Files

`app/main.py`

## Related

- The page decision: [page-gate.md](page-gate.md).
- Backend client: `georgian-arch-gen-backend/src/services/geometry/geometry.service.ts`.
  Backend rules for merging: `georgian-arch-gen-backend/specs/sheets.md`.
