"use client"

import { format } from "date-fns"
import { X } from "lucide-react"
import type { MarkerLocationContext } from "@/lib/locationProvenance"
import { localEventPlaceName } from "@/lib/localMapSelection"
import type { VisibleEvent } from "@/lib/queries"
import { selectionTimelineGroups } from "@/lib/selectionTimeline"
import { colorForEvent } from "@/lib/types"
import type { EventSelection } from "@/stores/rightPaneModeStore"

function itemTitle(ev: VisibleEvent): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const title =
    (typeof p.title === "string" && p.title) ||
    (typeof p.headline === "string" && p.headline) ||
    null
  if (title) return title
  // GDELT carries no headline — its export is a structured record of actor,
  // action and place. Falling through to the source name printed the literal
  // word "gdelt" on every row, which told the reader nothing. The CAMEO
  // action plus where it happened is the most this record can honestly say
  // (#733).
  const label = typeof p.action_label === "string" ? p.action_label : null
  if (label) {
    const where = typeof p.geo_name === "string" ? p.geo_name.split(",")[0]?.trim() : null
    return where ? `${label} · ${where}` : label
  }
  return ev.source
}

function clockTime(value: string): string {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? format(date, "HH:mm") : "--:--"
}

/** The right-pane view for a clicked map cluster / country news pile (#252):
 *  the list of events behind the bubble. Clicking a row drills into that
 *  single event's detail. Esc / × (handled by the parent) returns to base. */
export function ClusterListPanel({
  label,
  selections,
  area,
  onSelectEvent,
  onClose,
}: {
  label: string
  selections: EventSelection[]
  area?: {
    lat: number
    lon: number
    radiusKm: number
    labelKind: string
    dataState: "loading" | "ready" | "error"
  }
  onSelectEvent: (ev: VisibleEvent, location?: MarkerLocationContext) => void
  onClose: () => void
}) {
  const timeline = selectionTimelineGroups(selections)

  return (
    <aside className="flex h-full w-full flex-col gap-3 rounded-md border border-neutral-800 bg-neutral-950/95 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col">
          <span className="font-mono text-lg font-semibold tabular-nums leading-none text-cyan-400">
            {selections.length.toLocaleString()}
          </span>
          <span className="mt-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
            {area ? "local events" : "events"} · {label}
          </span>
          {area && (
            <span className="mt-1 font-mono text-[9px] tabular-nums text-neutral-600">
              {area.labelKind} · {area.lat.toFixed(5)}, {area.lon.toFixed(5)} · within {area.radiusKm.toLocaleString()} km
            </span>
          )}
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="text-neutral-500 hover:text-neutral-200"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {area?.dataState === "loading" ? (
        <p className="rounded-md border border-cyan-950 bg-cyan-950/20 px-3 py-4 text-xs leading-relaxed text-cyan-300/70">
          Loading complete positioned events for this ground area…
        </p>
      ) : area?.dataState === "error" ? (
        <p className="rounded-md border border-red-950 bg-red-950/20 px-3 py-4 text-xs leading-relaxed text-red-300/70">
          Complete local events could not be loaded. Retained rows may be incomplete.
        </p>
      ) : selections.length === 0 && area ? (
        <p className="rounded-md border border-neutral-800 bg-neutral-900/40 px-3 py-4 text-xs leading-relaxed text-neutral-500">
          No positioned events inside this area for the active time window.
        </p>
      ) : null}

      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto pr-1">
        {timeline.map((group) => (
          <section key={group.key}>
            <p className="px-2 pb-1 pt-2 font-mono text-[9px] uppercase tracking-wide text-neutral-600">
              {group.label}
            </p>
            <ul className="divide-y divide-neutral-800/60">
              {group.rows.map(({ number, selection: { event: ev, location, distanceKm } }) => {
                const place = location?.name?.trim() || localEventPlaceName(ev)
                const context = [
                  ev.source.replace(/^rss-/, ""),
                  place,
                  typeof distanceKm === "number"
                    ? `${distanceKm.toFixed(distanceKm < 1 ? 2 : 1)} km`
                    : null,
                ].filter(Boolean).join(" · ")
                return (
                  <li key={ev.id}>
                    <button
                      type="button"
                      onClick={() => onSelectEvent(ev, location)}
                      className="flex w-full items-start gap-2 rounded-md px-1 py-1 text-left transition-colors hover:bg-neutral-900/40"
                    >
                      <span className="w-4 shrink-0 pt-0.5 text-right font-mono text-[10px] tabular-nums text-neutral-600">
                        {number}
                      </span>
                      <span
                        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ backgroundColor: colorForEvent(ev) }}
                      />
                      <time
                        dateTime={ev.occurred_at}
                        title={new Date(ev.occurred_at).toLocaleString()}
                        className="w-10 shrink-0 pt-0.5 font-mono text-[10px] tabular-nums text-neutral-500"
                      >
                        {clockTime(ev.occurred_at)}
                      </time>
                      <span className="min-w-0 flex-1">
                        <span
                          className="block overflow-hidden text-[11.5px] leading-4 text-neutral-300"
                          style={{
                            display: "-webkit-box",
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: "vertical",
                          }}
                        >
                          {itemTitle(ev)}
                        </span>
                        <span className="mt-0.5 block truncate font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                          {context}
                        </span>
                      </span>
                      <span className="shrink-0 rounded border border-neutral-700 px-1 py-0.5 font-mono text-[9px] uppercase tracking-wide text-neutral-400">
                        {ev.category}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  )
}
