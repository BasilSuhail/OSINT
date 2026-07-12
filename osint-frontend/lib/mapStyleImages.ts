/** The minimal maplibre map surface we touch — kept as an interface so the
 *  behaviour is unit-testable with a fake map (no WebGL needed). */
export interface StyleImageHost {
  hasImage: (id: string) => boolean
  addImage: (id: string, image: { width: number; height: number; data: Uint8Array }) => void
}

/** OpenFreeMap's `dark` style references sprite ids its sprite sheet does not
 *  ship — `circle-11` (city/town labels) and `wood-pattern` (woodland fill).
 *  maplibre fires `styleimagemissing` for these constantly while panning /
 *  zooming, as matching features scroll into view.
 *
 *  The old handler answered with a full style reload (`styleReloadToken`),
 *  which flashed the whole map black AND re-triggered the same missing images —
 *  an endless reload loop, and the biggest perf drain on the 8GB Pi (#407).
 *
 *  maplibre's documented remedy is to register a 1×1 transparent placeholder so
 *  the event stops firing and nothing reloads; the icon simply renders empty
 *  (which it already did). Returns true when a placeholder was added — i.e. the
 *  id was genuinely missing. */
export function addMissingStyleImagePlaceholder(
  map: StyleImageHost,
  id: string | undefined,
): boolean {
  if (!id || map.hasImage(id)) return false
  map.addImage(id, { width: 1, height: 1, data: new Uint8Array(4) })
  return true
}
