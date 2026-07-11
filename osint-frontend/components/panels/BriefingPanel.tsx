"use client"

/**
 * Today's Briefing — the deck's landing card (#398).
 *
 * Pattern harvested from the proto-OSINT news-intelligence-platform
 * (TodaySignal + GPRGauge): open with the answer, not a hunt. Numbers are
 * this project's measured signals only — nothing asserted comes along.
 */

import useSWR from "swr"
import {
  confirmedClaims,
  corroborationTone,
  fetchCompositeMovers,
  fetchContestedStories,
  fetchTopStories,
  stressBand,
} from "@/lib/analytics"
import { countryName } from "@/lib/countryName"
import { Hint, Tip } from "./viz"

const REFRESH_MS = 5 * 60_000

function Block({
  title,
  hint,
  children,
}: {
  title: string
  hint: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
      <p className="mb-2 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
        <Hint term={title}>{hint}</Hint>
      </p>
      {children}
    </section>
  )
}

/** The deck's landing card: today's answer in four blocks. */
export function BriefingPanel() {
  const stories = useSWR(["stories-top", 24], () => fetchTopStories(24, 200), {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })
  const contested = useSWR("contested-top", fetchContestedStories, {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })
  const movers = useSWR("composite-movers", fetchCompositeMovers, {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })

  const best = (stories.data ?? [])
    .filter((s) => (s.corroboration ?? 0) > 0)
    .sort((a, b) => (b.corroboration ?? 0) - (a.corroboration ?? 0))[0]
  const bestConfirmed = best ? confirmedClaims(best.sensor_checks) : []
  const topContested = (contested.data ?? [])[0]
  const band = stressBand(movers.data?.global_mean ?? null)

  return (
    <div className="flex flex-col gap-3">
      <p className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
        the answer, not a hunt — today&apos;s most trustworthy story, most contested telling,
        biggest movers
      </p>

      <section className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
        <div className="flex items-baseline gap-3">
          <Tip
            content={
              <>
                {band.detail} Computed as the average of every country&apos;s latest composite
                stress score (0 calm → 1 stressed, each judged against its own history).
                <b className="text-neutral-100"> Honesty note:</b> this describes measured
                stress today — the composite&apos;s power to *predict* is still on public trial
                (see the scoreboard card).
              </>
            }
          >
            <span className={`font-mono text-2xl ${band.tone}`}>{band.word}</span>
          </Tip>
          <span className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
            world stress level
            {movers.data?.latest_month ? ` · ${movers.data.latest_month.slice(0, 7)}` : ""}
            {movers.data?.global_mean != null
              ? ` · mean ${movers.data.global_mean.toFixed(3)}`
              : ""}
          </span>
        </div>
      </section>

      <Block
        title="most trustworthy story right now"
        hint="The story with the highest confidence score in the last 24 hours: told by the most independent organisations, ideally confirmed by a physical sensor. Full story list lives on the stories card."
      >
        {!stories.data ? (
          <p className="font-mono text-[10px] text-neutral-500">loading…</p>
        ) : !best ? (
          <p className="font-mono text-[10px] text-neutral-500">
            nothing multi-source in the last 24h yet
          </p>
        ) : (
          <div className="flex items-center gap-2">
            <span
              className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] ${corroborationTone(best.corroboration)}`}
            >
              {best.owner_count} owners
            </span>
            <span className="min-w-0 flex-1 truncate text-sm text-neutral-200">{best.title}</span>
            {bestConfirmed.map((claim) => (
              <span
                key={claim}
                className="shrink-0 rounded border border-cyan-500/50 bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[9px] uppercase text-cyan-300"
              >
                ✓ {claim.replace("_", " ")}
              </span>
            ))}
          </div>
        )}
      </Block>

      <Block
        title="most contested telling"
        hint="The story whose country blocs word it most differently (divergence 0 = identical tellings, 1 = nothing in common). Contested narratives are a candidate early-warning signal — the disagreement exam on the scoreboard is testing exactly that."
      >
        {!contested.data ? (
          <p className="font-mono text-[10px] text-neutral-500">loading…</p>
        ) : !topContested ? (
          <p className="font-mono text-[10px] text-neutral-500">
            no cross-country tellings scored in the window yet
          </p>
        ) : (
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded border border-amber-500/50 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-amber-300">
              {topContested.divergence.toFixed(2)}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm text-neutral-200">
              {topContested.title}
            </span>
            <span className="shrink-0 font-mono text-[9px] text-neutral-500">
              {Object.entries(topContested.groups)
                .map(([c, n]) => `${countryName(c)} ×${n}`)
                .join(" vs ")}
            </span>
          </div>
        )}
      </Block>

      <Block
        title="biggest stress movers since last month"
        hint="Countries whose composite stress score changed most between the two latest scored months. ▲ rising stress, ▼ easing. Each country is judged against its own history — click it on the coverage card for the full sparkline."
      >
        {!movers.data ? (
          <p className="font-mono text-[10px] text-neutral-500">loading…</p>
        ) : movers.data.movers.length === 0 ? (
          <p className="font-mono text-[10px] text-neutral-500">
            needs two scored months — run `make backfill-signals` or wait for the hourly beat
          </p>
        ) : (
          <ul className="grid gap-1 sm:grid-cols-2">
            {movers.data.movers.map((m) => (
              <li key={m.country} className="flex items-baseline gap-2">
                <span
                  className={`w-10 shrink-0 text-right font-mono text-[11px] tabular-nums ${
                    m.delta > 0 ? "text-red-400" : "text-emerald-300"
                  }`}
                >
                  {m.delta > 0 ? "▲" : "▼"} {Math.abs(m.delta).toFixed(2)}
                </span>
                <span className="min-w-0 flex-1 truncate text-[12px] text-neutral-300">
                  {countryName(m.country)}
                </span>
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-neutral-500">
                  now {m.latest.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Block>

      <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-600">
        every number here is measured, versioned and explained on hover · details live on the
        stories / coverage / scoreboard cards
      </p>
    </div>
  )
}
