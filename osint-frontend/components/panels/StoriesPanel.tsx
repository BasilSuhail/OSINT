"use client"

import { useMemo, useState } from "react"
import useSWR from "swr"
import {
  confirmedClaims,
  corroborationTiers,
  corroborationTone,
  fetchTopStories,
  type StoryRow,
} from "@/lib/analytics"
import { BarRow, Hint, StatTile } from "./viz"

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
  return (
    <li className="flex items-center gap-3 border-b border-neutral-800/70 px-3 py-2 hover:bg-neutral-900/60">
      <span className="group/hint relative shrink-0 cursor-help">
        <span
          className={`inline-flex w-20 items-center justify-center rounded border px-1.5 py-0.5 font-mono text-[10px] tabular-nums ${corroborationTone(score)}`}
        >
          {story.owner_count} owner{story.owner_count === 1 ? "" : "s"}
        </span>
        <span className="pointer-events-none invisible absolute left-0 top-full z-50 mt-1.5 w-72 rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 font-sans text-[11px] leading-relaxed text-neutral-300 opacity-0 shadow-xl group-hover/hint:visible group-hover/hint:opacity-100">
          <b className="text-neutral-100">{story.owner_count} independent owners</b> told this
          story across {story.outlet_count} feeds ({story.member_count} articles). Wire copies
          and co-owned outlets collapse into one owner.
          <br />
          <b className="text-neutral-100">
            Confidence {score === null ? "not scored yet" : score.toFixed(3)}
          </b>{" "}
          — each extra independent owner halves the remaining doubt; a physical-sensor
          confirmation halves it once more. 0 = single unverified teller, 1 = near certainty.
        </span>
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-neutral-200" title={story.title}>
        {story.title}
      </span>
      {confirmed.map((claim) => (
        <span key={claim} className="group/hint relative shrink-0 cursor-help">
          <span className="rounded border border-cyan-500/50 bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-cyan-300">
            ✓ {claim.replace("_", " ")}
          </span>
          <span className="pointer-events-none invisible absolute right-0 top-full z-50 mt-1.5 w-64 rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 font-sans text-[11px] leading-relaxed text-neutral-300 opacity-0 shadow-xl group-hover/hint:visible group-hover/hint:opacity-100">
            A physical sensor (seismometer, fire satellite, disaster feed or market data)
            confirmed a matching <b className="text-neutral-100">{claim.replace("_", " ")}</b> at
            the story&apos;s place and time. Hardware cannot spin a narrative.
          </span>
        </span>
      ))}
      <span className="shrink-0 font-mono text-[9px] tabular-nums uppercase tracking-wide text-neutral-500">
        {relativeTime(story.last_seen)}
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
  const tiers = useMemo(() => corroborationTiers(data ?? []), [data])
  const maxTier = Math.max(1, ...tiers.map((t) => t.count))
  const multiOwner = (data ?? []).filter((s) => s.owner_count >= 2).length
  const sensorConfirmed = (data ?? []).filter(
    (s) => confirmedClaims(s.sensor_checks).length > 0,
  ).length

  return (
    <div className="flex flex-col gap-3">
      <p className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
        one row = one real-world story, however many outlets wrote it up · badge = how much to
        believe it
      </p>

      <section className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          <StatTile
            value={data?.length ?? 0}
            label="stories"
            hint="Distinct real-world stories in the selected window. Similar headlines are grouped every 30 minutes, so twenty write-ups of one earthquake count as one story."
          />
          <StatTile
            value={multiOwner}
            label="independently corroborated"
            tone="text-emerald-300"
            hint="Stories told by 2 or more independent organisations. Wire copies and co-owned feeds do not count twice — this is the honest confirmation count."
          />
          <StatTile
            value={sensorConfirmed}
            label="sensor-confirmed"
            tone="text-cyan-300"
            hint="Stories whose physical claim (earthquake, wildfire, disaster, market crash) was confirmed by an actual sensor — seismometers, fire satellites, disaster feeds or market data."
          />
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
            <Hint term="minimum owners">
              Hide stories told by fewer independent organisations than this. Set it to 2+ to
              hide everything only one organisation has said.
            </Hint>
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
      </section>

      <section className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
        <p className="mb-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
          <Hint term="confidence distribution — how much of today's news is corroborated?" wide>
            Every story gets a confidence score from 0 to 1: each additional independent owner
            halves the remaining doubt, and a physical-sensor confirmation halves it once more.
            These bars show how the current window&apos;s stories spread across the four tiers —
            most news is single-sourced, and seeing that is the point.
          </Hint>
        </p>
        {tiers.map((tier) => (
          <BarRow
            key={tier.label}
            label={tier.label}
            value={String(tier.count)}
            fraction={tier.count / maxTier}
            barClass={tier.tone}
            hint={tier.detail}
          />
        ))}
      </section>

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
        hover anything dotted or badged for what it means · owners = independent organisations
        (wire copies collapse) · ✓ = hardware confirmed the claim · rolling 72h window
      </p>
    </div>
  )
}
