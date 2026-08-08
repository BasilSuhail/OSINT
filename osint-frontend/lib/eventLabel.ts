import type { EventRow } from "./types"

/** The machine-coded action GDELT assigns a row — "Coerce", "Fight", "Consult".
 *
 * It is a classification of a sentence, not a headline, and a marker that
 * showed only this told the reader nothing about what happened (#768). It is
 * returned separately so it can be shown as what it is: a label the pipeline
 * applied, beside the story rather than instead of it. */
export function machineAction(ev: EventRow): string | null {
  const raw = (ev.payload as Record<string, unknown> | null)?.action_label
  return typeof raw === "string" && raw.trim() ? raw : null
}

/** Who published a row, or null when nobody did.
 *
 * Prefers the API's field (#768) and falls back to the article domain, so an
 * older API or a cached row still credits somebody. */
export function publisherOf(ev: EventRow): string | null {
  if (typeof ev.publisher === "string" && ev.publisher) return ev.publisher
  const url = (ev.payload as Record<string, unknown> | null)?.source_url
  if (typeof url !== "string" || !url.includes("://")) return null
  try {
    return new URL(url).hostname.replace(/^(?:www\.|m\.|amp\.)+/, "").toLowerCase() || null
  } catch {
    return null
  }
}

/** The article a row came from, for the (source) link. */
export function sourceUrlOf(ev: EventRow): string | null {
  const url = (ev.payload as Record<string, unknown> | null)?.source_url
  return typeof url === "string" && url.includes("://") ? url : null
}
