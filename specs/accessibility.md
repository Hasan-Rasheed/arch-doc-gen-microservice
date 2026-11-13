# Spec: Accessibility sheets (გ)

Accessible routes and door clearances, the way the album's accessibility sheets draw them.

## Rules (current truth)

- **Route:** a grey band of wheelchair width (0.9 m) from the lift or stair core, along the
  corridor, through each unit's entrance door and into **every named room**, reaching each room's
  far side.
  - The route is the shortest path through the walkable floor, kept clear of walls (centre at
    least 0.3 m from them).
  - A passage is carved through every door.
- **Turning circle:** one 1.5 m circle in every unit.
- **Door clearances:** teal boxes on both sides of every unit ↔ corridor and corridor ↔ stair
  door, 1.5 m deep and as wide as the door + 0.45 m on the latch side.
- **No wheelchair symbols** are drawn: they would claim which WC or entrance is accessible.
- **Only on residential-majority floors** (dwellings and hotels). This is a measured patch: on
  non-residential floors the route recall is about 0.
- **Default scale** is 1:200 when the sheet doesn't print one.

## Files

`app/access.py` (`accessible_routes`, `door_clearances`, `walk_grid`)

## Measured (gegmebi → album p.33–38)

| Measure | P | R |
|---|---|---|
| Route | 0.63–0.79 | 0.56–0.74 |
| Door boxes | 0.77–0.82 | 0.29–0.51 |

## Open (root causes found, not fixed)

- The scale is guessed from few room areas when the sheet doesn't print it.
- The route needs one connected walkable floor at any scale.

Both block non-residential accessibility sheets (see `docs/open_questions.md`).

## Related

[zones.md](zones.md), [egress.md](egress.md).
