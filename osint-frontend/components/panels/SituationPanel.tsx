"use client"

/**
 * The Situation card (#409) — the brain's plain-English read on the world
 * signal and the system's own health. Refreshes every 5 min; renders a
 * visible "resting" state when the brain has backed off (no narrative, or a
 * stale one) so backoff is honest, never hidden.
 */

import useSWR from "swr"
import { fetchBrainNarrative } from "@/lib/apiClient"

const REFRESH_MS = 5 * 60_000
//: Older than this and the card says the brain is resting.
const STALE_MS = 40 * 60_000

export function SituationPanel() {
  const { data } = useSWR("brain-narrative", fetchBrainNarrative, {
    refreshInterval: REFRESH_MS,
  })

  const narrative = data?.payload ?? null
  const createdAt = data?.created_at ? new Date(data.created_at).getTime() : 0
  const stale = !data?.present || Date.now() - createdAt > STALE_MS

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3 text-neutral-100">
      <header className="flex items-center justify-between">
        <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
          situation — the brain
        </p>
        {data?.model ? (
          <span className="font-mono text-[9px] text-neutral-600">{data.model}</span>
        ) : null}
      </header>

      {stale ? (
        <p className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3 text-sm text-neutral-400">
          Brain resting — the box is busy or no read is ready yet. Last narrative
          {data?.created_at ? ` from ${new Date(data.created_at).toLocaleTimeString()}` : " unavailable"}.
        </p>
      ) : null}

      {narrative ? (
        <>
          <h2 className="text-lg font-semibold leading-snug">{narrative.headline}</h2>
          {narrative.world ? <p className="text-sm text-neutral-300">{narrative.world}</p> : null}
          {narrative.system ? (
            <p className="text-sm text-neutral-400">{narrative.system}</p>
          ) : null}
          {narrative.watch && narrative.watch.length > 0 ? (
            <ul className="list-disc pl-5 text-sm text-neutral-300">
              {narrative.watch.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
