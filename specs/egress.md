# Spec: Escape routes (green lines on occupancy sheets)

The longest escape travel distance per floor, as the album draws it on the occupancy sheets.

## Rules (current truth)

- **Route:** from the point of a unit **farthest** from an exit stair, through the unit's door
  and along the corridor, to that stair.
- **How many lines:** one line per exit stair whose longest route is at least 60 % of the floor's
  longest (`LONG_SHARE`). The album draws one line on most floors and two where each stair serves
  a different block.
- **Label:** each line carries its length in metres. The legend row is "ევაკუაციის უდიდესი სავალი
  მანძილი" / "Longest escape travel distance".
- **The lengths go to the report** as measured facts (backend `measured-facts.ts`).
- **Detour guard:** a route more than 3× the straight line to a stair we couldn't reach is not
  drawn.
- **Where:** on residential floors only.
- **No separate escape-route sheet.** The album shows routes only on the occupancy plans; a
  separate sheet is parked.

## Files

`app/egress.py`

## Measured (gegmebi)

- Floors −1 to 2: P 0.30–0.36, R 0.36–0.51. The album routes to the farther north stair.
- Floor 3: P 0.95, R 0.71.
- Floor −2: none drawn, because the detour guard applied: the south stair is cut off by a line
  across its door (rechecked 2026-11-17), so the units only reach the north stair (55–61 m).
- Floor −3: none drawn: its single unit does not connect to the stair.
- Only stairs are exits. The album also counts doors straight to the outside ("გზა-კარი" on −2);
  see `docs/open_questions.md`.

## Related

[zones.md](zones.md), [sheet-drawing.md](sheet-drawing.md). Report use:
`georgian-arch-gen-backend/specs/report-writing.md`.
