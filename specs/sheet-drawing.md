# Spec: Drawing the sheets on the architect's original

How the colour sheets look.

## Rules (current truth)

- **The original sheet is kept unchanged:** vectors, title block, everything. It is placed on a
  new page in display orientation, and our layer goes on top as vectors. No zoomed crop pages are
  made.
- **Numbering and titles:** the title block is extended, so ა-100 becomes:
  - ა-100(ა) occupancy, „დაკავებულობის გეგმა";
  - ა-100(ბ) fire, „ხანძარსაწინააღმდეგო გეგმა";
  - ა-100(გ) accessibility, „მისაწვდომობის გეგმა".

  English titles are used when `lang=en`. Sheet numbers are left as the album prints them, even
  when two floors share one number.
- **Occupancy style:**
  - a **light tint** (14 %) in the album colour, a diagonal hatch, and a **solid darker outline**
    that follows the walls, one per unit;
  - colours: residential pure yellow (სც-2; hotels სც-1, same colour), business lavender (სქ),
    mercantile orange (სვ), assembly (თვ), institutional (დწ), educational (სგ), factory (სმ),
    storage (სწ), parking (სწ-2).
- **Fire style:** 2 h red, 1 h blue, 0.5 h magenta (sprinklered residential corridors only),
  dash-dot, 1.4 pt. The separation note is added when a dwelling ↔ other-use wall is 2 h.
- **Accessibility style:** a grey route band (45 %), turning circles, and teal door-clearance
  boxes.
- **Escape lines:** album green, with the length in metres ([egress.md](egress.md)).
- **Legend:** placed in an empty corner of the drawing, listing only what was drawn.
- **Font:** DejaVu Sans, which has Georgian glyphs (`SHEET_FONT`).
- **The symbols legend page** of the report is drawn by the frontend, in the same colours.

## Files

`app/sheet.py` (`CLASS_STYLE`, `FIRE_STYLE`, `SHEET_TITLE`, `occupancy_sheet`, `fire_sheet`,
`access_sheet`)

## Related

Frontend legend: `georgian-arch-gen/specs/symbols-legend.md`. Backend merge:
`georgian-arch-gen-backend/specs/sheets.md`.
