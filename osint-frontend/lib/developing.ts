/**
 * What the Situation card's pinned slot should show (#898).
 *
 * Three facts share one block, and the order they are checked in is the whole
 * behaviour:
 *
 *   - nothing qualifies      → show nothing; an empty slot is itself a finding
 *   - the fetch is failing   → say so, but not by deleting anything
 *   - stories are in hand    → show them
 *
 * The block used to answer the failure first, so a single failed revalidation
 * emptied a populated slot. SWR keeps the last good array when a refresh
 * fails — those stories were still held, and the panel was discarding data it
 * had. With the default retry backoff against a 60s refresh, one failed
 * request blanked the slot for anywhere from five seconds to a minute, which
 * is what "the stories sometimes disappear, usually it is fine" was.
 *
 * The failure itself is ordinary and is not what this fixes: a reloading dev
 * server restarting mid-request, a request timing out behind a heavy page
 * load. The point is that none of those should cost the reader what is already
 * on screen.
 *
 * Stated as a function rather than an `if` inside the component because the
 * suite runs without a DOM and cannot render the block. As a pure decision the
 * rule is testable, and the component is left with nothing to get wrong.
 */
export type DevelopingState =
  /** Nothing qualifies for a pin. Render nothing at all. */
  | "hidden"
  /** The fetch failed and there is nothing held from before to show. */
  | "unavailable"
  /** The fetch is failing, but earlier stories are still in hand. */
  | "stale"
  /** Current stories, fetched successfully. */
  | "live"

export function developingState(count: number, failed: boolean): DevelopingState {
  if (count > 0) return failed ? "stale" : "live"
  return failed ? "unavailable" : "hidden"
}
