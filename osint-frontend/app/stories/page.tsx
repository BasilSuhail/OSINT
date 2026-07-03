"use client"

import { useMemo, useState } from "react"
import useSWR from "swr"
import { SystemStatusBar } from "@/components/SystemStatusBar"
import { fetchTopStories, type StoryRow } from "@/lib/analytics"

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

function outletTone(count: number): string {
  if (count >= 5) return "border-cyan-500/50 bg-cyan-500/10 text-cyan-300"
  if (count >= 3) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
  if (count === 2) return "border-neutral-600 bg-neutral-800/60 text-neutral-300"
  return "border-neutral-800 bg-neutral-900 text-neutral-500"
}

function StoryLine({ story }: { story: StoryRow }) {
  return (
    <li className="flex items-center gap-3 border-b border-neutral-800/70 px-3 py-2 hover:bg-neutral-900/60">
      <span
        title={`${story.outlet_count} distinct outlets — the corroboration signal`}
        className={`inline-flex w-14 shrink-0 items-center justify-center rounded border px-1.5 py-0.5 font-mono text-[10px] tabular-nums ${outletTone(story.outlet_count)}`}
      >
        {story.outlet_count} src
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-neutral-200" title={story.title}>
        {story.title}
      </span>
      <span className="shrink-0 font-mono text-[9px] tabular-nums uppercase tracking-wide text-neutral-500">
        {story.member_count} art · {relativeTime(story.last_seen)}
      </span>
    </li>
  )
}

export default function StoriesPage() {
  const [hours, setHours] = useState<number>(24)
  const [minOutlets, setMinOutlets] = useState<number>(1)

  const { data, error, isLoading } = useSWR(
    ["stories-top", hours],
    () => fetchTopStories(hours, 200),
    { refreshInterval: REFRESH_MS, revalidateOnFocus: false },
  )

  const stories = useMemo(
    () => (data ?? []).filter((s) => s.outlet_count >= minOutlets),
    [data, minOutlets],
  )
  const multiOutlet = (data ?? []).filter((s) => s.outlet_count >= 2).length

  return (
    <div className="flex min-h-screen flex-col bg-neutral-950">
      <SystemStatusBar />
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-3 p-4">
        <header className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold text-neutral-100">Stories</h1>
            <p className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
              one row per real-world story · {data?.length ?? 0} stories · {multiOutlet} told by 2+
              outlets
            </p>
          </div>
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
              min outlets
              <select
                value={minOutlets}
                onChange={(e) => setMinOutlets(Number(e.target.value))}
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
          src = distinct outlets telling the story (corroboration input, WS-C) · clusters build
          over a rolling 72h window · assignments are append-only
        </p>
      </main>
    </div>
  )
}
