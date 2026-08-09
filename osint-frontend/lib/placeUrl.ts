import type { PlaceTarget } from "@/stores/placeStore"

/** Where to ask what a place is (#862).
 *
 * Pure, and separate from the fetch, because it is also the SWR cache key:
 * two right-clicks on the same point must produce the same string or the
 * screen refetches something it already has.
 *
 * Returns null when the target carries neither a full point nor a country.
 * Half a point is not a question the server can answer, and asking anyway
 * would spend a request to be told so.
 */
export function placeUrl(target: PlaceTarget, base: string): string | null {
  if (target.lat != null && target.lon != null) {
    return `${base}/geo/place?lat=${target.lat}&lon=${target.lon}`
  }
  if (target.iso) return `${base}/geo/place?iso=${target.iso}`
  return null
}
