/**
 * A photograph of the airframe under the dot.
 *
 * The map can say a military transport is over the Baltic; it cannot say what
 * that looks like, and for most readers the picture is the difference between a
 * symbol and an aircraft. The photos come from a public spotter archive, keyed
 * by the ICAO hex the transponder broadcasts — the one identifier on the row
 * that names an airframe rather than a flight.
 *
 * Three rules, because a picture makes a stronger claim than a row of numbers:
 *
 * - only by hex. A callsign is a flight and a registration is often the feed's
 *   guess; looking a photograph up by either risks showing the wrong aircraft
 *   beside real coordinates.
 * - only with a credit. The archive's licence is attribution, and an image
 *   nobody can be credited for is an image this console cannot use.
 * - only as a bonus. No photo, a refused request, an unfamiliar shape: the card
 *   renders exactly as it does without one. Nothing here is load-bearing.
 *
 * The photograph is of *an* airframe with this hex, taken at some point in the
 * past by somebody else. It is not evidence of anything happening now, and the
 * card says so where it is shown.
 */

const PHOTO_API = "https://api.planespotters.net/pub/photos/hex"

export interface AircraftPhoto {
  src: string
  /** Back to the photograph's page, which is where the licence lives. */
  link: string
  photographer: string
}

/** Where to ask, or null when there is nothing safe to ask by. */
export function aircraftPhotoUrl(hex: string | null | undefined): string | null {
  const id = hex?.trim().toLowerCase()
  if (!id) return null
  return `${PHOTO_API}/${encodeURIComponent(id)}`
}

function thumbnailSrc(photo: Record<string, unknown>): string | null {
  for (const key of ["thumbnail_large", "thumbnail"]) {
    const thumb = photo[key]
    if (thumb && typeof thumb === "object") {
      const src = (thumb as Record<string, unknown>).src
      if (typeof src === "string" && src) return src
    }
  }
  return null
}

/** The first photo, or null — including when the answer is a shape we do not
 *  recognise, because a photo is a bonus and never worth a guess. */
export function parseAircraftPhoto(answer: unknown): AircraftPhoto | null {
  if (!answer || typeof answer !== "object") return null
  const photos = (answer as Record<string, unknown>).photos
  if (!Array.isArray(photos) || photos.length === 0) return null
  const first = photos[0]
  if (!first || typeof first !== "object") return null
  const photo = first as Record<string, unknown>
  const src = thumbnailSrc(photo)
  if (!src) return null
  const link = typeof photo.link === "string" ? photo.link : ""
  const photographer = typeof photo.photographer === "string" ? photo.photographer.trim() : ""
  if (!photographer) return null
  return { src, link, photographer }
}
