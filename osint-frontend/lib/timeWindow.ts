/** What the time scrubber is currently showing, and whether that is "now" (#501).
 *
 * A scrubbed-back map renders identically to a live one. #340's third
 * acceptance criterion — "if the scrubber is off now, the UI says so
 * unmistakably" — was split out because nothing in the rail or over the map
 * said the view had stopped being current.
 *
 * Pure so the state machine is testable without a DOM: the component decides
 * how to paint it, this decides what it is.
 */

import { format } from "date-fns"

/** Slider steps are a minute, so anything inside one step is still "now". */
export const LIVE_TOLERANCE_MS = 60_000

export type TimeWindowState = "live" | "wide" | "historical"

export interface TimeWindowDescription {
  state: TimeWindowState
  /** True only for `live`. A wide window is current but not the default view. */
  isLive: boolean
  /** Short status word for the bar. */
  label: string
  /** What is actually on screen, including the window end. */
  detail: string
  /** Long form, for a title attribute. */
  title: string
  /** Whether a "go live" control should be offered. */
  canReturnToNow: boolean
}

export interface TimeWindowInput {
  windowEndOffsetMs: number
  windowLengthMs: number
  /** The window length that counts as the normal view. */
  defaultWindowMs: number
  /** Wall clock, injected so tests are not time-dependent. */
  now: number
}

function formatMoment(ms: number): string {
  return format(ms, "d MMM HH:mm")
}

function formatSpan(ms: number): string {
  const hours = ms / 3_600_000
  if (hours < 1) return `${Math.round(ms / 60_000)}m`
  if (hours < 48) return `${Math.round(hours)}h`
  return `${Math.round(hours / 24)}d`
}

/** Classify the current scrubber position.
 *
 * Three states, not two. `historical` is the correctness case — the map is
 * showing a moment that has passed. `wide` is a weaker warning: the window
 * still ends now, so the newest events are real, but it spans more than the
 * default view and so is not only "the current situation".
 *
 * Offset wins over length when both apply: being in the past is the stronger
 * claim, and stacking two warnings teaches people to ignore both.
 */
export function describeTimeWindow({
  windowEndOffsetMs,
  windowLengthMs,
  defaultWindowMs,
  now,
}: TimeWindowInput): TimeWindowDescription {
  const offset = Number.isFinite(windowEndOffsetMs) ? Math.max(0, windowEndOffsetMs) : 0
  const length = Number.isFinite(windowLengthMs) && windowLengthMs > 0 ? windowLengthMs : defaultWindowMs

  if (offset >= LIVE_TOLERANCE_MS) {
    const end = formatMoment(now - offset)
    return {
      state: "historical",
      isLive: false,
      label: "historical",
      detail: `to ${end}`,
      title: `Not live — the map shows events up to ${end}, ${formatSpan(offset)} ago. Click to return to now.`,
      canReturnToNow: true,
    }
  }

  if (length > defaultWindowMs) {
    return {
      state: "wide",
      isLive: false,
      label: "wide",
      detail: `${formatSpan(length)} window`,
      title: `Live, but showing a ${formatSpan(length)} window rather than the default ${formatSpan(defaultWindowMs)} — older events are on the map alongside current ones.`,
      canReturnToNow: true,
    }
  }

  return {
    state: "live",
    isLive: true,
    label: "live",
    detail: `${formatSpan(length)} window`,
    title: `Live — the map ends at now and shows the last ${formatSpan(length)}.`,
    canReturnToNow: false,
  }
}
