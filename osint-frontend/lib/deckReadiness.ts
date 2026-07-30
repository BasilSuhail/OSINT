/**
 * Which deck cards have something true to say (#695).
 *
 * The deck carried six cards and two of them showed nothing: the scoreboard's
 * every Brier was null because no prediction had matured, and briefing's stress
 * movers read 0.5 with a zero delta for every country because the composite is
 * flat. A dashboard whose stated ethos is refusing to publish numbers that mean
 * nothing should not open with two cards of them.
 *
 * So readiness is a property of the data, not a flag somebody maintains. The
 * scoreboard returns by itself the day a prediction grades — nothing to
 * remember, nothing to re-add.
 */

/** The scoreboard rows as `/journal/scoreboard` returns them. */
export interface ScoreboardReadinessRow {
  graded: number | null
}

/**
 * True once any prediction has actually been graded.
 *
 * Issued-but-pending is not enough: 501 of the pending forecasts carry the
 * constant 0.5 from the degenerate era (#685), so a count of issued rows would
 * bring the card back to display a track record that does not exist yet.
 *
 * `undefined` while SWR is still loading — treated as not ready, so the card
 * never flashes in and out on first paint.
 */
export function scoreboardIsReady(rows: ScoreboardReadinessRow[] | undefined): boolean {
  if (!rows) return false
  return rows.some((r) => (r.graded ?? 0) > 0)
}
