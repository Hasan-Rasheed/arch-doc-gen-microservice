# Spec: Rooms, units and occupancy zones

How rooms, units and №41 occupancy groups are found. This feeds every sheet.

## Rules (current truth)

1. **Rooms.**
   - The free space between boundary layers (walls, columns, doors, windows, rails) splits into
     connected regions. Door leaves and arcs close the doorways, so each room is its own region.
   - Doors on wall layers (ARCHICAD) are found from quarter arcs the size of a door leaf
     (0.55–1.4 m).
2. **Labels.**
   - Words that fall inside a region become that room's text (name + area).
   - Room labels are found by **text**, not by layer.
   - Names can be glued to numbers ("საძინებელი27.2"), and unit numbers drawn glyph by glyph
     are joined ("ოფისი-#06").
   - A real room has a name and a written area.
3. **Units.**
   - An anchor label (ბინა-01 = apartment, ოფისი 1 = office, …) starts a unit.
   - The unit grows from room to room through ordinary doors, but **never through fire-rated
     doors** (tagged კ-N / NN წთ, which are unit entrances) and never into stair, lift or
     corridor rooms.
   - It grows only into rooms with a real name, or compact pockets of 4 m² or less.
   - Private terraces and balconies are coloured.
   - Rooms reached by two units are shared and stay uncoloured, like corridors.
4. **Without unit words** (clinics, schools, offices):
   - Room **functions** map to №41 groups (`functions.py`), e.g. wards → დწ, labs and offices →
     სქ, pharmacy → სვ, conference → თვ, classrooms → სგ, storage → სწ, parking → სწ-2.
   - Support rooms take their neighbours' group.
   - Unknown names go to the backend's **LLM classifier**, which answers with a group or
     `unit:<group>`. The new group `transient` is სც-1.
5. **Cores and corridors without labels.**
   - **Stair and lift cores** are found from step numbers (a run of 5 or more) or dense
     stair-layer drawing in an unnamed room. A duplex's own stair stays in its apartment.
   - Big unnamed rooms with doors into 2 or more units are corridors.
   - Corridors split by glazed partitions are joined: narrow pieces of 3 m or less facing a
     corridor of 0.6 m or more.
   - An unlabeled pocket that also opens onto a bigger non-unit space stays outside the unit
     (door-swing bulges).
6. **Zone fill.** A unit's rooms merge into one region that includes the interior walls between
   them. Party walls between units of the same class are filled as one continuous zone, as the
   architects draw them.

## Files

`app/zones.py`, `app/functions.py`

## Measured (gegmebi → album p.27–32, scale 2.0)

| Floor | −3 | −2 | −1 | 1 | 2 | 3 |
|---|---|---|---|---|---|---|
| IoU | 0.95 | 0.88 | 0.89 | 0.85 | 0.87 | 0.90 |
| Spill | 1.8 % | 2.7 % | 1.7 % | 1.9 % | 2.2 % | 3.3 % |

For comparison, perfectly placed rectangles (the best the old AI approach could do) score
0.62–0.71 with about 30 % spill.

## Tried and reverted

- A scale-aware door reach: it hurt gegmebi floor 2 (IoU 0.87 → 0.79).
- Dashed lines as non-walls: dashes are also glazed partitions.

## Related

[fire.md](fire.md), [accessibility.md](accessibility.md), [egress.md](egress.md),
[sheet-drawing.md](sheet-drawing.md). Backend classifier:
`georgian-arch-gen-backend/specs/read-step.md`.
