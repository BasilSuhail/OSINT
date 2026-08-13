/** What the map asks the API for as it is moved, and what it keeps on screen
 *  while the answer is on its way (#952).
 *
 *  Both rules exist because a map is dragged, not stepped. Bounds read off a
 *  moving map are different every frame down to the metre, and treating each
 *  one as a new question meant a hard pan cancelled and restarted the request
 *  a dozen times and never finished any of them.
 */

export interface ViewportBounds {
  west: number
  south: number
  east: number
  north: number
}

/** Roughly five kilometres at the equator. Small enough that the extra ground
 *  it asks for is never noticeable, large enough that nudging the map does not
 *  invent a new question. */
export const VIEWPORT_GRID_DEG = 0.05

const floorTo = (value: number, grid: number) => Math.floor(value / grid) * grid
const ceilTo = (value: number, grid: number) => Math.ceil(value / grid) * grid
const round5 = (value: number) => Number(value.toFixed(5))

/**
 * Bounds snapped out to a fixed grid.
 *
 * Outward on every side, never inward: a box trimmed to the grid would drop
 * events that are on screen, and a mark missing from the edge of the map is a
 * worse fault than a few kilometres of ground fetched twice.
 */
export function quantizeBounds(
  bounds: ViewportBounds,
  grid: number = VIEWPORT_GRID_DEG,
): ViewportBounds {
  return {
    west: round5(Math.max(-180, floorTo(bounds.west, grid))),
    south: round5(Math.max(-90, floorTo(bounds.south, grid))),
    east: round5(Math.min(180, ceilTo(bounds.east, grid))),
    north: round5(Math.min(90, ceilTo(bounds.north, grid))),
  }
}

/**
 * Whether a snapshot taken at one point on the scrubber may still be drawn at
 * another.
 *
 * The tolerance while playing is what stops the map blinking empty once a
 * second: playback moves the window continuously and a snapshot is always
 * slightly behind it, but a snapshot less than one window length stale still
 * describes the time on screen.
 */
export function snapshotMatchesWindow(
  snapshotOffsetMs: number,
  settledOffsetMs: number,
  { playing, windowLengthMs }: { playing: boolean; windowLengthMs: number },
): boolean {
  if (snapshotOffsetMs === settledOffsetMs) return true
  return playing && Math.abs(snapshotOffsetMs - settledOffsetMs) < windowLengthMs
}

/**
 * Whether to interrupt the map with "loading".
 *
 * Only when there is nothing to interrupt. A refresh that has marks on screen
 * already is a refresh, and saying so over the top of them turned every drag
 * into a flashing banner. When the map is blank the message is the only thing
 * telling the reader that blank is temporary, so it stays.
 */
export function shouldAnnounceViewportLoading(
  loading: boolean,
  hasEventsOnScreen: boolean,
): boolean {
  return loading && !hasEventsOnScreen
}
