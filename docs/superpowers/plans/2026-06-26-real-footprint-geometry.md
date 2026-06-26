# Plan — Real hazard footprint geometry (issue #205)

Branch: `feat/real-footprint-geometry` (stacks on #204).
No DB migration — geometry stored in `events.payload.footprint_geojson` (already served by read-API).

## Verified endpoints
- **USGS**: detail GeoJSON `…/fdsnws/event/1/query?eventid={usgs_id}&format=geojson`
  → `properties.products.shakemap[0].contents["download/cont_mmi.json"].url`
  → FeatureCollection of MultiLineString MMI contours, each `properties.color` set. (Only quakes WITH a ShakeMap.)
- **GDACS**: `https://www.gdacs.org/contentdata/resources/{TYPE}/{id}/geojson_{id}_{episode}.geojson`
  → FeatureCollection w/ Point + real **Polygon** footprint. Default episode=1.

## Tasks (TDD)
1. **`app/enrichment/footprint.py`** — pure + IO:
   - `usgs_mmi_contour_url(detail) -> str|None`
   - `normalize_usgs_footprint(fc) -> dict|None` (keep contour lines, ensure color, fillOpacity=0)
   - `gdacs_footprint_url(event_type, event_id, episode=1) -> str`
   - `normalize_gdacs_footprint(fc, color) -> dict|None` (Polygon/MultiPolygon only, set color+fillOpacity)
   - `fetch_usgs_footprint`, `fetch_gdacs_footprint` (httpx, return None on any error)
   - `footprint_for_event(source, payload, color) -> dict|None` dispatcher
   - Tests: `tests/test_footprint_enrichment.py` (fixtures, no network).
2. **Persistence** — `set_event_footprint(session, event_id, geojson)` UPDATE helper (upsert skips existing).
3. **Task** — `enrich_hazard_footprints` in `tasks.py`: select hazard rows missing `payload.footprint_geojson`, fetch, update. Register beat (15-min, offset). One-shot backfill runnable now.
4. **Frontend** — `hazardSymbols.footprintFeatures`: if `payload.footprint_geojson` present → return its features (broaden `HazardFeature.geometry`), else synthesized circle fallback. Existing fill+line layers render lines (MMI color) + polygons (alert color).

## Acceptance
Quake w/ ShakeMap → real MMI contours; GDACS WF → real burn polygon. No-geometry events → circle fallback. tsc+eslint clean, pytest+vitest pass.
