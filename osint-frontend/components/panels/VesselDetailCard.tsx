"use client"

import { useEffect, useState } from "react"
import { Ship, X } from "lucide-react"
import { ageLabel } from "@/lib/presence"
import {
  suspectReason,
  vesselFacts,
  vesselTitle,
  type PresenceVessel,
} from "@/lib/vessels"
import { usePresenceStore } from "@/stores/presenceStore"

/**
 * One live vessel, opened by clicking its mark on the map (#954).
 *
 * The same standing as the aircraft card: something picked off the map, held
 * nowhere, with no row in the database and nothing to come back to tomorrow.
 * The card says so, because a panel that looks like every other detail panel
 * will otherwise be read as a record.
 *
 * The destination line is the one thing here that is not a measurement. It is
 * free text the crew typed into a form, it goes stale, and it is occasionally
 * a joke — so it is labelled as what the vessel *says*, never as where it is
 * going.
 */
export function VesselDetailCard({
  vessel,
  fetchedAt,
  onClose,
}: {
  vessel: PresenceVessel
  fetchedAt: string | null
  onClose: () => void
}) {
  //: Ticked rather than read once, so a card left open goes stale visibly.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5_000)
    return () => clearInterval(id)
  }, [])

  const facts = vesselFacts(vessel)
  const suspect = suspectReason(vessel)
  //: Whoever reported this refresh. Named on the card as well as the rail,
  //: because the card is where a reader decides whether to believe a mark.
  const sources = usePresenceStore((st) => st.vesselSources)

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex h-8 shrink-0 items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
          live vessel
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close vessel detail"
          className="text-neutral-500 transition-colors hover:text-neutral-200"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex items-center gap-2.5 pb-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-teal-500/15 text-teal-300">
          <Ship className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="truncate font-mono text-[15px] text-neutral-100">
            {vesselTitle(vessel)}
          </p>
          <p className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
            {vessel.category === "other" ? "type not transmitted" : vessel.category}
          </p>
        </div>
      </div>

      {/*: Said before the numbers, not after them. A reader who scrolls past
          this line and reads the position as a position has been misled by
          the layout rather than by the data. */}
      {suspect && (
        <p className="mb-2 rounded-lg border border-amber-400/30 bg-amber-400/10 px-2.5 py-2 text-[11px] leading-snug text-amber-200/90">
          This position is not believed: {suspect}. The transmission is real
          and is drawn where it claims to be, but something is interfering with
          it or imitating it, and the coordinates below are not where this
          vessel is.
        </p>
      )}

      <dl className="divide-y divide-white/5 overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
        {facts.map((f) => (
          <div key={f.label} className="flex items-baseline justify-between px-2.5 py-1.5">
            <dt className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
              {f.label}
            </dt>
            <dd className="truncate pl-2 font-mono text-[12px] tabular-nums text-neutral-200">
              {f.value}
            </dd>
          </div>
        ))}
        <div className="flex items-baseline justify-between px-2.5 py-1.5">
          <dt className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
            position
          </dt>
          <dd className="font-mono text-[12px] tabular-nums text-neutral-200">
            {vessel.lat.toFixed(3)}, {vessel.lon.toFixed(3)}
          </dd>
        </div>
      </dl>

      {/*: Who said so, and how long ago. Both are the reason to believe the
          mark, and the age is the reason to stop believing it. */}
      <p className="pt-2 font-mono text-[10px] uppercase tracking-wider text-neutral-600">
        {sources.length > 0 ? sources.join(" · ") : "source unnamed"}
        {fetchedAt ? ` · ${ageLabel(fetchedAt, now)}` : ""}
      </p>
      <p className="pt-1.5 text-[11px] leading-snug text-neutral-500">
        Presence, not evidence. This is where a transponder said the vessel was,
        heard by shore receivers covering one sea area. Nothing here is stored,
        so there is no history to open and nothing to cite.
      </p>
    </div>
  )
}
