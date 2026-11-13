# Open questions — geometry service

When one is answered, move the rule into the right `specs/<feature>.md` and delete it here.
Project-wide status: `../ROADMAP.md`.

## Decisions waiting for the user

| # | Question | Recommendation |
|---|---|---|
| G1 | Place fire equipment symbols by the №41 rules, or keep only the architect's? | Keep as now (see `georgian-arch-gen-backend/docs/open_questions.md` B1) |
| G2 | Measure corridor and door widths and the façade-to-boundary distances, so the report gets them as measured facts? | Yes; it is the next accuracy step after the rerun |

## Waiting for the client (samples)

- 1–2 finished albums of non-residential buildings (hotel, office, shop, school). Without them
  there is no answer key for non-residential fire and accessibility sheets, and no sheet
  conventions for those types.
- Real non-layered inputs with their albums (A15).
- Clean TRIBE plans, exported with layers.

## Open work, not blocked by a decision

| Item | Notes |
|---|---|
| Accessibility on non-residential floors | Root causes: the scale is guessed from few room areas; the route needs one connected floor at any scale |
| N2c-2 | Grand Master 42 at 2×: its corridor is a region the door rule misses; office N06's upper rooms; the second stair |
| N8-2 | No-layer PDFs: close the window and door openings (thin pens) so rooms form. 14 of 15 such sample pages fail on "no units", not on leaks |
| Hotel rough spots | An uncoloured room, a corridor fire line, a missing route |
| US office | Merged and split rooms; "zones not closed by walls" on 2 pages |
| Ardstudio p6 | Coverage 0.67, under the 0.75 gate |
| Georgian CAD-font OCR | Parked (inputs are master files; scans are rare) |
| Escape routes as their own sheet, parking layout sheet | Parked (not in the album) |
