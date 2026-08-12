import type { DatasetHealthSummary, HealthBand } from "./systemHealth"
import type { IngestHealthRow, SourceCoverageRow } from "./types"

/** The word each health band is called on screen.
 *
 * `warn` reads as "degraded" and `ok` as "online" because the monitor names a
 * source's condition, not the severity of a log line. The mapping lives here
 * so the button, the group headers and any future surface cannot drift into
 * calling the same band two different things.
 */
export const BAND_LABEL: Record<HealthBand, string> = {
  offline: "offline",
  warn: "degraded",
  stale: "stale",
  ok: "online",
}

/** Worst first. The whole point of the monitor is that offline is what you
 *  look at, so the order is fixed rather than sortable. */
export const BAND_ORDER: HealthBand[] = ["offline", "warn", "stale", "ok"]

export interface BandGroup {
  band: HealthBand
  label: string
  count: number
  datasets: DatasetHealthSummary[]
}

/** Groups sources under one coloured header per band, worst band first.
 *
 * Grouping is what lets the colour be explained once. A flat list has to
 * repeat a red dot beside eleven rows and still never says what red means;
 * a header that reads "offline 3" carries the dot, the word and the count in
 * one line, and the rows below inherit all three.
 */
export function groupByBand(datasets: DatasetHealthSummary[]): BandGroup[] {
  return BAND_ORDER.map((band) => {
    const members = datasets.filter((dataset) => dataset.status === band)
    return { band, label: BAND_LABEL[band], count: members.length, datasets: members }
  }).filter((group) => group.count > 0)
}

export interface BandCount {
  band: HealthBand
  count: number
}

/** What the collapsed button shows: a dot and a number per unhealthy band.
 *
 * Online is deliberately absent. A count of what is working is not a reason
 * to open anything, and the button has to be readable at a glance from the
 * corner of the eye — three numbers at most, none of them words.
 */
export function attentionCounts(datasets: DatasetHealthSummary[]): BandCount[] {
  return BAND_ORDER.filter((band) => band !== "ok")
    .map((band) => ({ band, count: datasets.filter((d) => d.status === band).length }))
    .filter((entry) => entry.count > 0)
}

/** How long ago, in the shortest form that stays unambiguous.
 *
 * Minutes below the hour, hours and minutes below the day, days and hours
 * above it. A row whose age reads "4h 12m" says more than one reading "stale"
 * — the band already said stale, the number says how badly.
 */
export function formatAge(iso: string | null, nowMs: number): string {
  if (!iso) return "—"
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return "—"
  const minutes = Math.max(0, Math.round((nowMs - then) / 60_000))
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`
  return `${Math.floor(hours / 24)}d ${String(hours % 24).padStart(2, "0")}h`
}

export interface DailyInsert {
  day: string
  inserted: number
}

/** Rows written per day, summed across every source.
 *
 * The footer graph answers "is anything still arriving", which no per-source
 * row can answer on its own. `inserted_rows` is the honest number — rows that
 * reached the database — and falls back to accepted only when a source does
 * not report inserts.
 */
export function insertedByDay(rows: IngestHealthRow[]): DailyInsert[] {
  const totals = new Map<string, number>()
  for (const row of rows) {
    const written = row.inserted_rows ?? row.accepted_rows ?? 0
    totals.set(row.day, (totals.get(row.day) ?? 0) + written)
  }
  return [...totals.entries()]
    .map(([day, inserted]) => ({ day, inserted }))
    .sort((a, b) => a.day.localeCompare(b.day))
}

/** Events recorded in the coverage window, summed across sources. `recent` is
 *  the windowed count; `total` is everything ever stored and would quietly
 *  turn a freshness readout into a lifetime one. */
export function totalRecentRows(rows: SourceCoverageRow[]): number {
  return rows.reduce((sum, row) => sum + (row.recent ?? 0), 0)
}

/** Sparkline geometry: one point per day, scaled to the tallest day.
 *
 * Returned as unit coordinates so the caller owns the pixel size. A flat run
 * of zeroes returns an empty path rather than a straight line pinned to the
 * floor, which would read as a measurement when it is an absence of one.
 */
export function sparklinePoints(days: DailyInsert[]): { x: number; y: number }[] {
  const peak = Math.max(...days.map((d) => d.inserted), 0)
  if (days.length < 2 || peak <= 0) return []
  return days.map((day, index) => ({
    x: index / (days.length - 1),
    y: 1 - day.inserted / peak,
  }))
}
