"use client"

import { useMemo, useState } from "react"
import useSWR from "swr"
import {
  confirmedClaims,
  corroborationTone,
  fetchTopStories,
  type StoryRow,
} from "@/lib/analytics"

const REFRESH_MS = 60_000
const WINDOWS = [
  { hours: 6, label: "6h" },
  { hours: 24, label: "24h" },
  { hours: 72, label: "72h" },
] as const

function relativeTime(iso: string): string {
  const deltaMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.max(0, Math.round(deltaMs / 60_000))
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function StoryLine({ story }: { story: StoryRow }) {
  const confirmed = confirmedClaims(story.sensor_checks)
  const score = story.corroboration
  const badgeTitle =
    `${story.owner_count} independent owners (${story.outlet_count} feeds) — ` +
    (score === null
      ? "corroboration not yet scored"
      : `corroboration ${score.toFixed(3)} (corroboration-v1.0)`)
  return (
    <li className="flex items-center gap-3 border-b border-neutral-800/70 px-3 py-2 hover:bg-neutral-900/60">
      <span
        title={badgeTitle}
        className={`inline-flex w-14 shrink-0 items-center justify-center rounded border px-1.5 py-0.5 font-mono text-[10px] tabular-nums ${corroborationTone(score)}`}
      >
        {story.owner_count} src
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-neutral-200" title={story.title}>
        {story.title}
      </span>
      {confirmed.map((claim) => (
        <span
          key={claim}
          title={`physical sensor confirmed: ${claim} (see sensor_checks)`}
          className="shrink-0 rounded border border-cyan-500/50 bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-cyan-300"
        >
          ✓ {claim.replace("_", " ")}
        </span>
      ))}
      <span className="shrink-0 font-mono text-[9px] tabular-nums uppercase tracking-wide text-neutral-500">
        {story.member_count} art · {relativeTime(story.last_seen)}
      </span>
    </li>
  )
}

/** Story clusters — one row per real-world story. Deck card / fullscreen body. */
export function StoriesPanel() {
  const [hours, setHours] = useState<number>(24)
  const [minOwners, setMinOwners] = useState<number>(1)

  const { data, error, isLoading } = useSWR(
    ["stories-top", hours],
    () => fetchTopStories(hours, 200),
    { refreshInterval: REFRESH_MS, revalidateOnFocus: false },
  )

  const stories = useMemo(
    () => (data ?? []).filter((s) => s.owner_count >= minOwners),
    [data, minOwners],
  )
  const multiOwner = (data ?? []).filter((s) => s.owner_count >= 2).length
  const sensorConfirmed = (data ?? []).filter(
    (s) => confirmedClaims(s.sensor_checks).length > 0,
  ).length

  return (
    <div className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
          {data?.length ?? 0} stories · {multiOwner} told by 2+ independent owners ·{" "}
          {sensorConfirmed} sensor-confirmed
        </p>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            {WINDOWS.map((w) => (
              <button
                key={w.hours}
                onClick={() => setHours(w.hours)}
                className={
                  hours === w.hours
                    ? "rounded border border-cyan-500/50 bg-cyan-500/10 px-2 py-0.5 font-mono text-[10px] text-cyan-300"
                    : "rounded border border-neutral-800 px-2 py-0.5 font-mono text-[10px] text-neutral-400 hover:text-neutral-200"
                }
              >
                {w.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-wide text-neutral-500">
            min owners
            <select
              value={minOwners}
              onChange={(e) => setMinOwners(Number(e.target.value))}
              className="rounded border border-neutral-800 bg-neutral-900 px-1 py-0.5 text-[10px] text-neutral-200"
            >
              {[1, 2, 3, 5].map((n) => (
                <option key={n} value={n}>
                  {n}+
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <section className="overflow-hidden rounded-xl border border-neutral-800 bg-neutral-900/50">
        {error ? (
          <p className="p-4 font-mono text-[11px] text-red-400">
            stories API unreachable — is the backend running?
          </p>
        ) : isLoading ? (
          <p className="p-4 font-mono text-[11px] text-neutral-500">loading…</p>
        ) : stories.length === 0 ? (
          <p className="p-4 font-mono text-[11px] text-neutral-500">
            no stories in this window — clustering runs every 30 minutes
          </p>
        ) : (
          <ul>
            {stories.map((story) => (
              <StoryLine key={story.id} story={story} />
            ))}
          </ul>
        )}
      </section>

      <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-600">
        src = independent owners (wire copies + co-owned feeds collapse) · badge tone =
        corroboration-v1.0 (each extra owner halves doubt, a sensor confirmation halves it
        again) · ✓ = physical sensor confirmed the claim · rolling 72h window, append-only
      </p>
    </div>
  )
}
