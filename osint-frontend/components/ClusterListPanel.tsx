"use client"

import { formatDistanceToNowStrict } from "date-fns"
import { X } from "lucide-react"
import type { MarkerLocationContext } from "@/lib/locationProvenance"
import type { VisibleEvent } from "@/lib/queries"
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

/** The right-pane view for a clicked map cluster / country news pile (#252):
 *  the list of events behind the bubble. Clicking a row drills into that
 *  single event's detail. Esc / × (handled by the parent) returns to base. */
export function ClusterListPanel({
  label,
  selections,
  onSelectEvent,
  onClose,
}: {
  label: string
  selections: EventSelection[]
  onSelectEvent: (ev: VisibleEvent, location?: MarkerLocationContext) => void
  onClose: () => void
}) {
  return (
    <aside className="flex h-full w-full flex-col gap-3 rounded-md border border-neutral-800 bg-neutral-950/95 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col">
          <span className="font-mono text-lg font-semibold tabular-nums leading-none text-cyan-400">
            {selections.length.toLocaleString()}
          </span>
          <span className="mt-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
            events · {label}
          </span>
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

      <ul className="-mx-1 flex-1 space-y-0.5 overflow-y-auto pr-1">
        {selections.map(({ event: ev, location }) => (
          <li key={ev.id}>
            <button
              type="button"
              onClick={() => onSelectEvent(ev, location)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-neutral-800/60"
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: colorForEvent(ev) }}
              />
              <span className="w-16 shrink-0 whitespace-nowrap font-mono text-[10px] text-neutral-500">
                {formatDistanceToNowStrict(new Date(ev.occurred_at), { addSuffix: false })}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs text-neutral-200">{itemTitle(ev)}</span>
                <span className="block truncate font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                  {ev.source.replace(/^rss-/, "")}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}
