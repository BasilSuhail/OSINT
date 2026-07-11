"use client"

import { useMemo, useState } from "react"
import useSWR from "swr"
import {
  confirmedClaims,
  corroborationTiers,
  corroborationTone,
  fetchStoryMembers,
  fetchTopStories,
  type StoryRow,
} from "@/lib/analytics"
import { countryName } from "@/lib/countryName"
import { BarRow, Hint, StatTile, Tip } from "./viz"

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

function StoryMembers({ storyId }: { storyId: string }) {
  const { data, error } = useSWR(["story-members", storyId], () => fetchStoryMembers(storyId))
  if (error)
    return <p className="px-4 pb-2 font-mono text-[10px] text-red-400">members unavailable</p>
  if (!data) return <p className="px-4 pb-2 font-mono text-[10px] text-neutral-500">loading…</p>
  return (
    <ul className="border-l-2 border-neutral-800 bg-neutral-950/40 px-4 py-1">
      {data.map((m, i) => (
        <li key={i} className="flex items-baseline gap-2 py-0.5">
          <Tip
            className="shrink-0"
            content={
              <>
                <b className="text-neutral-100">{m.outlet}</b> — independent owner{" "}
                <b className="text-neutral-100">{m.owner}</b>, editorial voice based in{" "}
                {m.origin_country ? countryName(m.origin_country) : "unknown"}. Join similarity{" "}
                {m.similarity.toFixed(2)}: how close this headline sits to the story&apos;s
                centre (1.00 founded the story).
              </>
            }
          >
            <span className="font-mono text-[9px] uppercase tracking-wide text-cyan-300/80">
              {m.outlet}
            </span>
          </Tip>
          <span className="min-w-0 flex-1 truncate text-[12px] text-neutral-300">{m.title}</span>
          <span className="shrink-0 font-mono text-[9px] tabular-nums text-neutral-600">
            {m.origin_country ? countryName(m.origin_country) : "—"} · {m.similarity.toFixed(2)}
          </span>
        </li>
      ))}
      <li className="py-0.5 font-mono text-[8px] uppercase tracking-wide text-neutral-600">
        who said what — each line is one outlet&apos;s telling of this same story
      </li>
    </ul>
  )
}

function StoryLine({
  story,
  expanded,
  onToggle,
}: {
  story: StoryRow
  expanded: boolean
  onToggle: () => void
}) {
  const confirmed = confirmedClaims(story.sensor_checks)
  const score = story.corroboration
  return (
    <li
      className="cursor-pointer border-b border-neutral-800/70 hover:bg-neutral-900/60"
      onClick={onToggle}
    >
      <div className="flex items-center gap-3 px-3 py-2">
      <Tip
        className="shrink-0"
        content={
          <>
            <b className="text-neutral-100">{story.owner_count} independent owners</b> told this
            story across {story.outlet_count} feeds ({story.member_count} articles). Wire copies
            and co-owned outlets collapse into one owner.
            <br />
            <b className="text-neutral-100">
              Confidence {score === null ? "not scored yet" : score.toFixed(3)}
            </b>{" "}
            — each extra independent owner halves the remaining doubt; a physical-sensor
            confirmation halves it once more. 0 = single unverified teller, 1 = near certainty.
          </>
        }
      >
        <span
          className={`inline-flex w-20 items-center justify-center rounded border px-1.5 py-0.5 font-mono text-[10px] tabular-nums ${corroborationTone(score)}`}
        >
          {story.owner_count} owner{story.owner_count === 1 ? "" : "s"}
        </span>
      </Tip>
      <span className="min-w-0 flex-1 truncate text-sm text-neutral-200" title={story.title}>
        {story.title}
      </span>
      {confirmed.map((claim) => (
        <Tip
          key={claim}
          className="shrink-0"
          content={
            <>
              A physical sensor (seismometer, fire satellite, disaster feed or market data)
              confirmed a matching <b className="text-neutral-100">{claim.replace("_", " ")}</b>{" "}
              at the story&apos;s place and time. Hardware cannot spin a narrative.
            </>
          }
        >
          <span className="rounded border border-cyan-500/50 bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-cyan-300">
            ✓ {claim.replace("_", " ")}
          </span>
        </Tip>
      ))}
      <span className="shrink-0 font-mono text-[9px] tabular-nums uppercase tracking-wide text-neutral-500">
        {relativeTime(story.last_seen)} {expanded ? "▾" : "▸"}
      </span>
      </div>
      {expanded ? <StoryMembers storyId={story.id} /> : null}
    </li>
  )
}

/** Story clusters — one row per real-world story. Deck card / fullscreen body. */
export function StoriesPanel() {
  const [hours, setHours] = useState<number>(24)
  const [minOwners, setMinOwners] = useState<number>(1)
  const [expandedId, setExpandedId] = useState<string | null>(null)

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
          <Hint term="confidence distribution — how much of today's news is corroborated?">
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
              <StoryLine
                key={story.id}
                story={story}
                expanded={expandedId === story.id}
                onToggle={() => setExpandedId((v) => (v === story.id ? null : story.id))}
              />
            ))}
          </ul>
        )}
      </section>

      <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-600">
        click a story to see who said what · hover anything dotted or badged for what it means ·
        owners = independent organisations (wire copies collapse) · ✓ = hardware confirmed the
        claim · rolling 72h window
      </p>
    </div>
  )
}
