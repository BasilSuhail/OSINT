"use client"

import { useEffect, useState } from "react"
import { Plane, X } from "lucide-react"
import { useAircraftDetailStore } from "@/stores/aircraftDetailStore"
import { aircraftFacts, aircraftTitle, ageLabel } from "@/lib/presence"

/**
 * One live aircraft, opened by clicking its mark on the map.
 *
 * Everything here came off a transponder seconds ago and is held nowhere else:
 * no row in the database, no id to link to, nothing to come back to tomorrow.
 * The card says that out loud, because a panel that looks like every other
 * detail panel will otherwise be read as a record.
 */
export function AircraftDetailCard() {
  const aircraft = useAircraftDetailStore((s) => s.aircraft)
  const fetchedAt = useAircraftDetailStore((s) => s.fetchedAt)
  const closeAircraft = useAircraftDetailStore((s) => s.closeAircraft)

  //: The age is the whole claim: a live layer that will not say when it last
  //: heard anything is indistinguishable from a frozen one. Ticked here rather
  //: than read once, so a card left open goes stale visibly.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5_000)
    return () => clearInterval(id)
  }, [])

  if (!aircraft) return null

  const facts = aircraftFacts(aircraft)
  const distress = aircraft.kind === "distress"

  return (
    <div className="flex h-full w-full flex-col bg-neutral-950">
      <div className="flex h-8 shrink-0 items-center justify-between px-3">
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
          live aircraft
        </span>
        <button
          type="button"
          onClick={closeAircraft}
          aria-label="Close aircraft detail"
          className="text-neutral-500 transition-colors hover:text-neutral-200"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <div className="flex items-center gap-2.5 pb-3">
          <span
            className={
              distress
                ? "grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-red-500/15 text-red-300"
                : "grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-sky-500/15 text-sky-300"
            }
          >
            <Plane className="h-4 w-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="truncate font-mono text-[15px] text-neutral-100">
              {aircraftTitle(aircraft)}
            </p>
            <p
              className={
                distress
                  ? "font-mono text-[10px] uppercase tracking-widest text-red-300/90"
                  : "font-mono text-[10px] uppercase tracking-widest text-neutral-500"
              }
            >
              {distress ? "distress squawk" : "military"}
            </p>
          </div>
        </div>

        <dl className="divide-y divide-white/5 overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
          {facts.map((f) => (
            <div key={f.label} className="flex items-baseline justify-between px-2.5 py-1.5">
              <dt className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                {f.label}
              </dt>
              <dd className="font-mono text-[12px] tabular-nums text-neutral-200">{f.value}</dd>
            </div>
          ))}
          <div className="flex items-baseline justify-between px-2.5 py-1.5">
            <dt className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
              position
            </dt>
            <dd className="font-mono text-[12px] tabular-nums text-neutral-200">
              {aircraft.lat.toFixed(3)}, {aircraft.lon.toFixed(3)}
            </dd>
          </div>
        </dl>

        {/*: Who said so, and how long ago. Both are the reason to believe the
            dot, and the age is the reason to stop believing it. */}
        <p className="pt-2 font-mono text-[10px] uppercase tracking-wider text-neutral-600">
          adsb.lol · ODbL{fetchedAt ? ` · ${ageLabel(fetchedAt, now)}` : ""}
        </p>
        <p className="pt-1.5 text-[11px] leading-snug text-neutral-500">
          Presence, not evidence. This position is where a transponder said the
          aircraft was seconds ago. Nothing here is stored, so there is no
          history to open and nothing to cite.
        </p>
      </div>
    </div>
  )
}
