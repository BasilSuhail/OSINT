"use client"

/**
 * The story pop-out card (#448) — one story, told in full. Opens to the LEFT of
 * the deck (same width) when any story row is clicked; the deck stays the main
 * card. Name on top, then the trust read (corroboration, contested telling,
 * sensor verdicts) and every member article grouped by the outlet's origin
 * country — the "who tells it, and how differently" view.
 */

import useSWR from "swr"
import { confirmedClaims, fetchStoryDetail, type StoryDetail } from "@/lib/analytics"
import { countryName } from "@/lib/countryName"
import { groupByOrigin, groupByVoice, singleVoiceCaveat } from "@/lib/situation"
import { contestedVerdict, storyVerdict } from "@/lib/verdicts"
import { useStoryDetailStore } from "@/stores/storyDetailStore"

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-1 mt-4 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
      {children}
    </p>
  )
}

function ContestedTelling({ detail }: { detail: StoryDetail }) {
  if (detail.divergence === null || !detail.divergence_groups) return null
  const groups = Object.entries(detail.divergence_groups).sort((a, b) => b[1] - a[1])
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
      <div className="flex items-baseline justify-between">
        <SectionLabel>contested telling</SectionLabel>
        <span className="font-mono text-lg text-neutral-100">{detail.divergence.toFixed(2)}</span>
      </div>
      <p className="font-mono text-[11px] text-neutral-300">
        {groups.map(([code, n], i) => (
          <span key={code}>
            {countryName(code)} ×{n}
            {i < groups.length - 1 ? " vs " : ""}
          </span>
        ))}
      </p>
      <p className="mt-1 text-[12px] leading-snug text-neutral-400">
        {contestedVerdict({ divergence: detail.divergence, groups: detail.divergence_groups })}
      </p>
    </div>
  )
}

function TrustRead({ detail }: { detail: StoryDetail }) {
  const confirmed = confirmedClaims(detail.sensor_checks)
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
      <div className="flex items-baseline justify-between">
        <SectionLabel>corroboration</SectionLabel>
        <span className="font-mono text-lg text-neutral-100">
          {detail.corroboration !== null ? detail.corroboration.toFixed(2) : "—"}
        </span>
      </div>
      <p className="text-[12px] leading-snug text-neutral-400">
        {storyVerdict({
          owner_count: detail.owner_count,
          corroboration: detail.corroboration,
          confirmed,
        })}
      </p>
      {Object.keys(detail.sensor_checks).length > 0 ? (
        <p className="mt-2 font-mono text-[10px] text-neutral-500">
          {Object.entries(detail.sensor_checks).map(([claim, verdict]) => (
            <span key={claim} className="mr-2">
              {claim}: {verdict === "confirmed" ? "✓ confirmed" : verdict}
            </span>
          ))}
        </p>
      ) : null}
    </div>
  )
}

//: Per-class label colors (#488) — state stands out, independent reads green.
const VOICE_COLORS: Record<string, string> = {
  mainstream: "text-neutral-300",
  regional: "text-cyan-300/70",
  state: "text-amber-300/80",
  independent: "text-emerald-300/70",
}

function Voices({ detail }: { detail: StoryDetail }) {
  const groups = groupByVoice(detail.members)
  if (groups.length === 0) return null
  const caveat = singleVoiceCaveat(groups)
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
      <SectionLabel>voices — how framings differ</SectionLabel>
      {caveat ? <p className="mb-2 text-[11px] text-amber-300/80">{caveat}</p> : null}
      <div className="flex flex-col gap-2">
        {groups.map((g) => (
          <div key={g.voice}>
            <p
              className={`font-mono text-[10px] uppercase tracking-wide ${
                VOICE_COLORS[g.voice] ?? "text-neutral-400"
              }`}
            >
              {g.voice} ×{g.members.length}
            </p>
            <ul className="border-l-2 border-neutral-800 pl-3">
              {g.members.slice(0, 2).map((m, i) => (
                <li key={i} className="py-0.5 text-[12px] leading-snug text-neutral-300">
                  <span className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
                    {m.outlet}
                  </span>{" "}
                  — {m.title}
                </li>
              ))}
              {g.members.length > 2 ? (
                <li className="py-0.5 text-[10px] text-neutral-600">
                  +{g.members.length - 2} more
                </li>
              ) : null}
            </ul>
          </div>
        ))}
      </div>
    </div>
  )
}

function Tellers({ detail }: { detail: StoryDetail }) {
  const groups = groupByOrigin(detail.members)
  if (groups.length === 0) return null
  return (
    <div>
      <SectionLabel>who tells it — {detail.members.length} articles</SectionLabel>
      <div className="flex flex-col gap-3">
        {groups.map((g) => (
          <div key={g.origin ?? "unknown"}>
            <p className="mb-1 font-mono text-[10px] uppercase tracking-wide text-cyan-300/70">
              {g.origin ? countryName(g.origin) : "origin unknown"} ×{g.members.length}
            </p>
            <ul className="border-l-2 border-neutral-800 pl-3">
              {g.members.map((m, i) => (
                <li key={i} className="py-1 text-[12px] leading-snug text-neutral-300">
                  <span className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
                    {m.outlet} ·{" "}
                    {new Date(m.occurred_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                  <br />
                  {m.title}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  )
}

function daysRunning(firstSeen: string, lastSeen: string): string {
  const days = (new Date(lastSeen).getTime() - new Date(firstSeen).getTime()) / 86_400_000
  if (days < 1) return "developing today"
  const n = Math.floor(days)
  return `running ${n} day${n === 1 ? "" : "s"}`
}

export function StoryDetailCard() {
  const storyId = useStoryDetailStore((s) => s.storyId)
  const closeStory = useStoryDetailStore((s) => s.closeStory)
  const { data, error } = useSWR(storyId ? ["story-detail", storyId] : null, () =>
    fetchStoryDetail(storyId as string),
  )

  if (!storyId) return null
  return (
    <div className="flex h-full flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between p-3 pb-2">
        <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
          story — detail
        </p>
        <button
          onClick={closeStory}
          aria-label="close story detail"
          className="font-mono text-[11px] text-neutral-500 hover:text-neutral-200"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        {error ? (
          <p className="text-sm text-red-400">Story unavailable.</p>
        ) : !data ? (
          <p className="text-sm text-neutral-500">loading…</p>
        ) : (
          <>
            <h2 className="text-lg font-semibold leading-snug">{data.title}</h2>
            <p className="mt-1 font-mono text-[10px] text-neutral-500">
              {data.category ? `${data.category} · ` : ""}
              {data.escalating === "yes" ? "escalating ↑ · " : ""}
              {daysRunning(data.first_seen, data.last_seen)} ·{" "}
              {data.outlet_count} outlets · {data.owner_count} independent owners
            </p>
            {data.gist ? (
              <p className="mt-2 text-[13px] leading-snug text-neutral-300">{data.gist}</p>
            ) : null}

            <div className="mt-3 flex flex-col gap-3">
              <ContestedTelling detail={data} />
              <Voices detail={data} />
              <TrustRead detail={data} />
            </div>

            <Tellers detail={data} />
          </>
        )}
      </div>
    </div>
  )
}
