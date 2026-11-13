# Spec: Scoring harness and samples

How changes are measured. A geometry change is kept only if the scores hold.

## Rules (current truth)

- **Answer keys come from finished albums** whose colour markup sits on CAD layers.
  - gegmebi ↔ the architects' album (`Samples/Gegmebi - Sample 3/`):
    - album pages 27–32 are occupancy, 33–38 accessibility, 39–44 fire;
    - each covers floors −3 to 3, which are gegmebi pages 1–6;
    - album page 28 is shifted 17.8 / 10.9 pt, so matching aligns before comparing.
  - `DownloadServlet.pdf` (without "(1)") is a **different building**.
- **Second building:** `second_key.py` strips another office's markup layers to get the raw plan.
  It covers Grand Master 42 (offices) and the `new/` clinic.
- **Generated inputs:** `ifc_samples.py` builds, per storey of public BIM models (ifc-bench, with
  per-model licences), a layered, a flattened and a scan-like PDF plus a room answer key, into
  `Samples/Generated - …`. `score_rooms.py` scores them.
- **Survey:** `survey.py` runs every sample through the page gate and reports which pages get
  sheets and why the rest fall back. `--classes` uses the real LLM classes.
- **Guards:**
  - The gegmebi scores and the test suite must not drop; otherwise the change is reverted.
  - Scorers default to the service scale (2 px/pt).
- **Samples are tests, never special cases.** No rule may name a sample or hard-code its values.
- **All Python runs in Docker**; the host has no pip.

## Commands (from the ArchiDocGen root)

```bash
RUN='docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -w /work/georgian-arch-gen-geometry archidocgen-geometry:dev'
eval $RUN python -m pytest -q -p no:cacheprovider tests                       # ~10 min
eval $RUN env RUN_SURVEY=1 python -m pytest -q -p no:cacheprovider tests/test_samples.py
eval $RUN python -m harness.survey [--classes]
eval $RUN python -m harness.run_zones --source "/work/Samples/Gegmebi - Sample 3/gegmebi input.pdf"
eval $RUN python -m harness.second_key
eval $RUN python -m harness.score_rooms
```

Outputs go to `out/`, which git ignores.

## Files

| File | What |
|---|---|
| `harness/samples.py` | Where the sample PDFs live (`../Samples/`, one folder per project) |
| `harness/answer_key.py` | Ground truth from an architects' album whose derived sheets are on CAD layers |
| `harness/build.py` | Builds the occupancy answer key from the gegmebi album and scores reference baselines |
| `harness/score.py` | Scores a predicted occupancy colouring against an answer key |
| `harness/run_zones.py` | Predicts zones on every answer-key sheet (album p.27-32) and scores them |
| `harness/fire_key.py` | Fire-line ground truth from the album (`DownloadServlet (1).pdf`) |
| `harness/run_fire.py` | Runs `app/fire.py` on every fire answer-key sheet (p.39-44), scores, writes previews |
| `harness/run_access.py` | Runs `app/access.py` on every accessibility answer-key sheet (p.33-38), scores, writes previews |
| `harness/second_key.py` | Answer keys from other offices' sheets, to check that gegmebi tuning carries over |
| `harness/ifc_samples.py` | Builds `Samples/Generated - …` plans from public BIM (IFC) models, with their answer keys |
| `harness/score_rooms.py` | Room-level score against the IFC answer keys |
| `harness/survey.py` | Page checks over every sample PDF: per page, would it get a geometry sheet and why not |
| `harness/room_classes.json` | Saved LLM room classes for the samples (from the backend's `npm run classify:samples`), read by `survey --classes` |
| `tests/test_zones.py` | Regression floor for occupancy zones vs the gegmebi key |
| `tests/test_fire.py` | Fire-rated walls vs the album's fire sheets, and the fire sheet |
| `tests/test_access.py` | Accessible routes vs the album's accessibility sheets |
| `tests/test_sheet.py` | Occupancy sheets drawn on the original pages, and the API around them |
| `tests/test_generalize.py` | Rules that make other offices' plans work (cores without labels, doors on walls, …) |
| `tests/test_second_key.py` | Second-building answer keys |
| `tests/test_samples.py` | Every sample through the page checks (needs `RUN_SURVEY=1`) |
| `tests/test_answer_key.py` | The album's occupancy sheets line up with their source pages |
| `tests/test_extract.py` | PDF reading (`app/extract.py`): display space, layers, room labels |
| `tests/test_layers.py` | Layer dictionary (`app/layers.py`) and legacy Georgian fonts (`app/acadnusx.py`) |

## Related

The scores are listed in each feature's spec: [zones.md](zones.md), [fire.md](fire.md),
[accessibility.md](accessibility.md), [egress.md](egress.md), [page-gate.md](page-gate.md).
