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

`harness/*.py`, `tests/*.py`

## Related

The scores are listed in each feature's spec: [zones.md](zones.md), [fire.md](fire.md),
[accessibility.md](accessibility.md), [egress.md](egress.md), [page-gate.md](page-gate.md).
