# CLAUDE.md: ArchiDocGen geometry service

This file is read at the start of every session in this repo. The project-wide file is
`../CLAUDE.md`.

## Rules live in `specs/`

`specs/<feature>.md` is the **current truth** for how each feature behaves.
- When a rule changes, update its spec, including its measured scores, in the same commit as the
  code.
- If a spec and the code disagree, find out which is right and fix the other.
- Open decisions go to `docs/open_questions.md`; outdated notes go to `docs/archive/`.

## Specs

| Spec | Feature |
|---|---|
| [api.md](specs/api.md) | `/health`, `/extract`, `/plan`, `/sheets`, token, parallel pages |
| [page-gate.md](specs/page-gate.md) | Which pages get geometry sheets, which kinds, and why the rest fall back |
| [pdf-reading.md](specs/pdf-reading.md) | Display space, layer dictionary, walls without layers (styles, image), legacy Georgian fonts, OCR, scale |
| [zones.md](specs/zones.md) | Rooms, units, №41 groups from room functions, cores, corridors, zone fill |
| [fire.md](specs/fire.md) | 2 h / 1 h / 0.5 h rated walls from №41 (§713.4, §420.2, Tables 1018.1, 508.4) |
| [accessibility.md](specs/accessibility.md) | Accessible route bands, turning circles, door clearances |
| [egress.md](specs/egress.md) | Longest escape-route lines and lengths |
| [sheet-drawing.md](specs/sheet-drawing.md) | Sheets on the architect's original: numbering, colours, legend |
| [harness.md](specs/harness.md) | Answer keys, survey, generated BIM inputs, guards, commands |
| [deployment.md](specs/deployment.md) | Docker image, Railway, `GEOMETRY_TOKEN`, workers and memory |

**Related specs in the other repos:**
- Backend `../georgian-arch-gen-backend/specs/`:
  - `sheets.md`: geometry merge, fallback to AI sheets, catalog;
  - `read-step.md`: `/plan` and the LLM room classifier;
  - `report-writing.md`: measured facts from the sheets;
  - `report-facts.md`: the sprinkler answer behind `sprinklered`.
- Frontend `../georgian-arch-gen/specs/` (branch `v2`):
  - `symbols-legend.md`: the legend page in the same colours;
  - `sheet-drawing.md`: AI and signage sheets drawn in the browser.

## Production

- **Railway:** https://arch-doc-gen-microservice-production.up.railway.app (health: `/health`). The backend calls it with `GEOMETRY_SERVICE_URL` and
  `GEOMETRY_TOKEN`; if it is unreachable, the backend falls back to AI sheets.
- Backend: https://arch-doc-gen-backend-production.up.railway.app. Frontend:
  https://arch-doc-gen.vercel.app.
- Setup steps: [specs/deployment.md](specs/deployment.md).

## Repo

- GitHub: `Hasan-Rasheed/arch-doc-gen-microservice`, branch **`main`**.
- Stack: Python 3.12, FastAPI + uvicorn, PyMuPDF (fitz), OpenCV, NumPy, Tesseract.
  **Everything Python runs in Docker**; the host has no pip.
- Layout:
  - `app/`: the service (see the specs);
  - `harness/`: scoring and samples;
  - `tests/`: pytest, about 180 tests, about 10 minutes;
  - `out/`: harness output, ignored by git.
- Commands: see [specs/harness.md](specs/harness.md). Rebuild the image after any change in
  `app/`.

## Client and team

- **Client:** Zura. The users are Georgian architects and CAD users in multi-user studio
  workspaces.
- **Built by:** Hasan Rasheed (developer).
- **Inputs** are architects' master (working) PDFs, mostly vector, often with CAD layers. Scans
  are rare.

## Working rules

- **Never push.** One commit per task, per repo.
- **Any building, any input.** Every rule is general. Samples are tests, never special cases;
  never add rules one building type at a time.
- **Guards:** the gegmebi scores and the test suite must not drop. Otherwise revert and report.
- **Fix card:** each fix states its expected result, whether it is primary or a patch, and for a
  patch the blocker, who resolves it and what to ask the client.
- **Never invent equipment placements or wheelchair symbols** on sheets.
- Update `../ROADMAP.md` (status) and the spec (rules and scores) when a task finishes.
