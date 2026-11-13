# Spec: Page gate (which pages get geometry sheets)

A page gets geometry sheets only when the result can be trusted. Otherwise it falls back to the
AI sheet, and the reason is returned.

## Rules (current truth)

`page_verdict` in `app/main.py` decides, in the same way for the API and for `harness/survey.py`:

1. **Walls must exist.** The page needs CAD layers, or synthetic layers built from line styles or
   the page image ([pdf-reading.md](pdf-reading.md)). Otherwise: "no CAD layers".
2. **At least one unit** must be found. Otherwise: "no units found".
3. **Zones must stay closed by walls.** If the zones cover more than 40 % of the sheet
   (`MAX_ZONE_SHARE`), they have leaked: "zones not closed by walls".
4. **At least 75 % of the named rooms must be in units** (`MIN_NAMED_COVERAGE`). Otherwise: "most
   rooms not in units".
   - Named rooms are real rooms: a name plus a written area, inside the building, not
     circulation. Open balconies and terraces count as explained.

Which kinds a page that passes gets (`_rule_kinds`):
- **occupancy:** always;
- **fire:** when at least half of the labelled units are dwellings, hotels or offices
  (`FIRE_VALIDATED_GROUPS`);
- **accessibility:** when at least half of the units are dwellings or hotels.

The last two are **measured patches**: non-residential accessibility route recall is about 0,
and clinic fire precision is at most 0.16. They are lifted only when real albums of those
building types score well.

## Files

`app/main.py` (`page_verdict`, `_rule_kinds`, `unclassified_names`)

## Measured (`python -m harness.survey --classes`, 2026-10-28)

- **Real inputs:** 17 of 51 pages get CAD sheets: Ardstudio 7/10, gegmebi 6/7, Sample 1 3/22,
  samushao hotel 1/1, att 0/1, oda 0/10 (a heating plan, which is correct).
- **Generated plans:** 16 of 27.

## Related

[api.md](api.md), [harness.md](harness.md). Backend fallback:
`georgian-arch-gen-backend/specs/sheets.md`.
