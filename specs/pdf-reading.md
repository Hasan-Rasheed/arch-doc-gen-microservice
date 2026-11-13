# Spec: Reading the PDF (layers, walls, text)

Turning any architectural PDF (layered, flattened or scanned) into walls and positioned words.

## Rules (current truth)

- **Display space.** All coordinates are converted to display space (PDF points with the page
  rotation applied). gegmebi's pages are stored rotated 270°.
- **Layers are hints, not proof.** `app/layers.py` classifies layer names into categories: walls,
  columns, doors, windows, rails, hatch, text, tags, dimensions, furniture, grid, site, frame and
  so on. The human-readable source is `../Layer Dictionary.md`.
  - Names mislead: `kedeli` holds site retaining walls, `სვლაგეზები` holds toilets, `COLUMN`
    holds the main concrete walls. Geometry and area checks decide.
  - Our own dictionary is used, never one office's list. ARCHICAD names are included (walls on
    `Structural - Bearing`).
- **Pages without CAD layers** (flattened exports, prints to PDF, scans) get walls in two ways:
  - `styles.py`: synthetic layers by line style. Dark or grey solid fills are the wall poché, and
    the pens running along them are the wall lines.
  - `image_walls.py`: walls from the page image (the primary source since 2026-10-28).
    - Ink is grey level ≤ 150. Pieces no bigger than letters (4 mm) are dropped.
    - Parallel outlines up to 0.32 m apart are one wall; walls are at least 0.08 m thick and
      0.6 m long.
    - Glazing gaps up to 8 m are bridged where thin lines run through, and empty gaps up to a
      door's width (1.2 m) are bridged.
- **Text.**
  - Words are read from the text layer, with their positions.
  - A word is split where the glyphs jump along the text direction.
  - **Legacy Georgian CAD fonts** (AcadNusx, AcadMtavr, Avaza, AvantGardeMtavruli) store Georgian
    as Latin letters; `acadnusx.py` decodes them. BPG fonts are real Unicode and are left alone.
  - Room keywords match in any spelling (`acadnusx.fold`): Georgian, AcadNusx Latin and plain
    Latin.
- **Scans** with no text layer get words from **Tesseract** (`ocr.py`):
  - Georgian + English, sparse-text mode, about 290 dpi, confidence ≥ 55.
  - Georgian CAD-font OCR is **parked**: inputs are master files and scans are rare.
- **Light fills and strokes** are CAD wipeouts (white masks), not walls.
- **Drawing scale:** taken from the "1:100" text on the sheet. If there is none, it is estimated
  from the written room areas against the measured ones, snapped to a standard scale.

## Files

`app/extract.py`, `app/layers.py`, `app/styles.py`, `app/image_walls.py`, `app/ocr.py`,
`app/acadnusx.py`, `../Layer Dictionary.md`.

## Measured (rooms found as one region, `harness/score_rooms.py`)

| Plan | Layered | Flattened | Scan |
|---|---|---|---|
| KIT office | 94–100 % | 94–100 % | 94–100 % |
| US office (wbdg) | 77–85 % | 75–85 % | 75–85 % |
| TUM hotel | 85–91 % | 50–78 % | 50–64 % |

**Known limit:** a façade drawn as one thin line stays open.

## Related

[zones.md](zones.md), [page-gate.md](page-gate.md).
