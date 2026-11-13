# Spec: Fire sheets (ბ): rated walls

Fire-resistance lines drawn the way the album's fire sheets mark them, with ratings from the №41
text.

## Rules (current truth)

- **2 h (red):**
  - the building **envelope**, where the enclosed floor meets outside air (open terraces and
    balconies count as outside);
  - every wall around a **stair or lift core** when the core connects **4 or more storeys**,
    counting basements (§713.4 / §1022.2). Otherwise the core is 1 h.
- **1 h (blue):**
  - walls **between dwellings** (§420.2 fire partitions, §708.3);
  - walls **between a unit and a corridor**, per Table 1018.1, by the unit's group and the floor's
    occupant load (Table 1004.1.2):
    - სც over 10 occupants: 1 h (0.5 h sprinklered, drawn magenta);
    - დწ at any load: 1 h (none sprinklered);
    - other groups over 30 occupants: 1 h (none sprinklered);
    - on a shared corridor, the strictest group wins.
  - Walls between rooms of one non-residential group are not rated.
- **Different non-residential groups:** Table 508.4 (separated occupancies), e.g. parking ↔
  offices 2 h (1 h sprinklered); offices ↔ shops none.
- **A dwelling toward any other use:** 2 h without sprinklers, 1 h with, and never below the 1 h
  of §420.2. Whenever such a 2 h wall is drawn, the legend notes the alternative: non-separated
  occupancies (§508.3) allow 1 h, which is what the album draws.
- **Sprinklered values apply only when the project says it is sprinklered** (the backend sends
  `sprinklered`). The default is unsprinklered, which matches the album.
- **Sanity check:** a floor with 2 or more units but no 1 h wall falls back to the AI.
- **Equipment symbols** (extinguishers, alarms) are never placed. Symbols the architect drew stay,
  because the sheet is the original.
- **Method:**
  - The floor inside the envelope is divided among its spaces (unit, corridor, core) by nearest
    room, so every wall is split down its middle, and its rating follows from the two spaces it
    separates.
  - Lines are straightened across doorways.
  - A stair label in a corridor, or a lift drawn with its door open, doesn't turn the hall into a
    core.

## Files

`app/fire.py` (`fire_lines`, `corridor_rating`, `separation_508`, `floor_load`)

## Measured (gegmebi → album p.39–44, lines within 5 pt)

| Floor | 2 h P / R | 1 h P / R |
|---|---|---|
| −3 | 0.82 / 0.96 | — |
| −2 | 0.78 / 0.87 | 0.61 / 0.78 |
| −1 | 0.74 / 0.85 | 0.86 / 0.93 |
| 1 | 0.47 / 0.83 | 0.93 / 0.53 → recall 0.92 after A9 |
| 2 | 0.52 / 0.82 | 0.87 / 0.92 |
| 3 | 0.50 / 0.77 | 0.59 / 0.52 |

- The album doesn't mark every exterior wall, which caps 2 h precision.
- Office floor (GM42): P 0.40 / R 0.48. Clinic: P 0.02–0.16, which is why the page gate patch
  exists.

## Related

[zones.md](zones.md), [page-gate.md](page-gate.md). Report side (sprinkler fact):
`georgian-arch-gen-backend/specs/report-facts.md`.
