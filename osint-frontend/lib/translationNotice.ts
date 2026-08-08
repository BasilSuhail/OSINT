import type { EventRow } from "@/lib/types"

/**
 * Whether a reader is looking at the publisher's words (#837).
 *
 * #835 translates headlines from desks that do not publish in English, so the
 * resolver, severity and clustering — all Latin-script — can read them. It
 * stores the original verbatim and records which model produced the English.
 * Nothing displayed any of that, which is half a rule: a translated headline
 * arrived looking exactly like one the outlet wrote, attributed to a publisher
 * this project counts as an independent teller.
 *
 * From the live run on the Arabic desk:
 *
 *     original    رودري المرشح التالي …      "Rodri, the next candidate …"
 *     displayed   "Barcelona's next candidate …"
 *
 * Good enough to resolve and rank. Not good enough to read as the outlet's
 * words, and the reader had no way to tell which they were looking at.
 *
 * One helper, read by every surface. Two definitions of "is this translated"
 * would eventually disagree, and the disagreement would be invisible.
 */

export type TranslationStatus = "ok" | "failed"

export interface TranslationNotice {
  status: TranslationStatus
  /** Which model produced it, so a bad translation traces to a version
   *  rather than to the outlet. */
  model: string | null
  /** The publisher's actual words, when we kept them. Null on a failure,
   *  where the displayed headline *is* the original. */
  original: string | null
}

function payloadOf(ev: EventRow): Record<string, unknown> {
  return (ev.payload ?? {}) as Record<string, unknown>
}

/** The translation notice for a row, or null when nothing was translated.
 *
 * Null is the common case by a wide margin — the great majority of the corpus
 * is published in English and must not gain furniture. */
export function translationNotice(ev: EventRow): TranslationNotice | null {
  const raw = payloadOf(ev).title_translation
  if (!raw || typeof raw !== "object") return null
  const note = raw as Record<string, unknown>
  const status = note.status === "failed" ? "failed" : note.status === "ok" ? "ok" : null
  if (status === null) return null
  const original = payloadOf(ev).title_original
  return {
    status,
    model: typeof note.model === "string" ? note.model : null,
    original: status === "ok" && typeof original === "string" ? original : null,
  }
}

/** The short marker shown beside the headline.
 *
 * Deliberately words rather than an icon: a flag or a globe glyph would need
 * a legend, and the whole point is that no legend should stand between a
 * reader and knowing who wrote the sentence. */
export function translationLabel(notice: TranslationNotice): string {
  return notice.status === "ok" ? "machine-translated" : "not translated"
}

/** The full explanation, for a title attribute or a tooltip.
 *
 * The label carries the fact; this carries the detail, including the original
 * so a reader of the source language can check the claim themselves. */
export function translationDetail(notice: TranslationNotice): string {
  if (notice.status === "failed") {
    return (
      "This headline is in its original language. Translation was attempted and failed, " +
      "so these are the publisher's own words, untranslated."
    )
  }
  const by = notice.model ? ` by ${notice.model}` : ""
  const original = notice.original ? `\n\nOriginal: ${notice.original}` : ""
  return `Machine-translated${by} — not the publisher's own wording.${original}`
}
