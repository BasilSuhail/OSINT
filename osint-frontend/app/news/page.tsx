"use client"

/**
 * The reading page (/news).
 *
 * The console is an instrument: dense, monospaced, everything at once, built
 * to be watched. This is the other posture — a page you read. Same data, same
 * API, no map, no scrubber, one column of stories at a size a person can sit
 * with.
 *
 * It is a separate URL on purpose. Two tabs can be open at once, the console
 * keeps running while this is read, and someone who only wants the news can go
 * straight here without loading a map at all.
 *
 * Room to grow: the page is a list of sections stacked in one column, so a new
 * section (charts, a country page, the audit) is a component added to the
 * stack, not a redesign.
 *
 * Selecting a story slides the column left rather than covering it — the list
 * stays legible beside what it opened, which is the whole reason the reading
 * page has room the card did not.
 */

import { useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import Link from "next/link"
import {
  fetchDevelopingStories,
  fetchTopStories,
  type DevelopingStory,
  type StoryRow,
} from "@/lib/analytics"
import { rankStories, relativeAge, type RankedStory } from "@/lib/newsRanking"
import { StoryReader } from "@/components/news/StoryReader"
import { AskDock } from "@/components/news/AskDock"

const REFRESH_MS = 60_000
//: The window the page reads over. Long enough that a story running for two
//: days is still on the page under its own latest filing.
const TOP_HOURS = 48
const TOP_LIMIT = 60
//: The ceiling /stories/developing enforces (api.py: `le=10`).
const DEVELOPING_LIMIT = 10

function Meta({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500">
      {children}
    </span>
  )
}

function StoryLine({
  ranked,
  rank,
  now,
  active,
  onOpen,
}: {
  ranked: RankedStory<StoryRow>
  rank: number
  now: number
  active: boolean
  onOpen: () => void
}) {
  const { story, reasons } = ranked
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-current={active ? "true" : undefined}
      className={`group grid w-full grid-cols-[2.5rem_1fr] gap-x-5 border-t border-neutral-800/70 py-6 text-left transition-colors first:border-t-0 ${
        active ? "bg-neutral-900/40" : "hover:bg-neutral-900/25"
      }`}
    >
      <span
        className={`pt-1 text-right font-mono text-[11px] tabular-nums transition-colors ${
          active ? "text-cyan-300" : "text-neutral-600 group-hover:text-neutral-400"
        }`}
      >
        {String(rank).padStart(2, "0")}
      </span>
      <span className="min-w-0">
        <span className="mb-2 flex items-center gap-3">
          <Meta>{relativeAge(story.last_seen, now)}</Meta>
          {story.escalating === "escalating" && (
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-amber-400/90">
              escalating
            </span>
          )}
          {story.category && <Meta>{story.category}</Meta>}
        </span>
        <span
          className={`block font-serif text-[1.4rem] leading-[1.28] tracking-[-0.011em] transition-colors ${
            active ? "text-neutral-50" : "text-neutral-100 group-hover:text-white"
          }`}
        >
          {story.title}
        </span>
        {story.gist && (
          <span className="mt-2 block max-w-[42rem] text-[0.95rem] leading-relaxed text-neutral-400">
            {story.gist}
          </span>
        )}
        <span className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
          {reasons.map((reason) => (
            <Meta key={reason}>{reason}</Meta>
          ))}
        </span>
      </span>
    </button>
  )
}

function Section({
  label,
  note,
  children,
}: {
  label: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <section className="mb-14">
      <div className="mb-5 flex items-baseline gap-3 border-b border-neutral-800 pb-2">
        <h2 className="font-mono text-[10px] uppercase tracking-[0.22em] text-neutral-400">
          {label}
        </h2>
        {note && (
          <p className="font-mono text-[10px] tracking-[0.06em] text-neutral-600">{note}</p>
        )}
      </div>
      {children}
    </section>
  )
}

export default function NewsPage() {
  const [openId, setOpenId] = useState<string | null>(null)
  //: One clock for the whole render. Reading `Date.now()` per row would make
  //: two stories filed in the same minute disagree about how old they are.
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenId(null)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const { data: developing, error: developingError } = useSWR<DevelopingStory[]>(
    "news:developing",
    () => fetchDevelopingStories(DEVELOPING_LIMIT),
    { refreshInterval: REFRESH_MS },
  )
  const { data: top, error: topError } = useSWR<StoryRow[]>(
    "news:top",
    () => fetchTopStories(TOP_HOURS, TOP_LIMIT),
    { refreshInterval: REFRESH_MS },
  )

  const pinnedIds = useMemo(() => new Set((developing ?? []).map((s) => s.id)), [developing])
  const pinned = useMemo(() => rankStories(developing ?? [], now), [developing, now])
  //: A pinned story is not repeated below; the page would otherwise rank the
  //: same thing twice and read as two stories.
  const rest = useMemo(
    () => rankStories((top ?? []).filter((s) => !pinnedIds.has(s.id)), now),
    [top, pinnedIds, now],
  )

  const loading = developing === undefined && top === undefined
  const failed = developingError && topError
  const open = openId !== null

  return (
    <div className="min-h-dvh bg-neutral-950 text-neutral-100">
      <header className="sticky top-0 z-20 border-b border-neutral-800/80 bg-neutral-950/85 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[100rem] items-center justify-between px-6">
          <div className="flex items-baseline gap-4">
            <span className="font-serif text-[1.15rem] tracking-[-0.01em] text-neutral-50">
              The Situation
            </span>
            <span className="hidden items-center gap-2 sm:flex">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
              <Meta>live · ranked by independent tellers</Meta>
            </span>
          </div>
          <Link
            href="/"
            className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500 transition-colors hover:text-cyan-300"
          >
            console ↗
          </Link>
        </div>
      </header>

      <div className="px-6">
        {/*: Centred, not left-hugging. Laid out as a plain row inside a very
            wide container the column pinned to the left edge and left a third
            of the screen empty beside it, which reads as a page missing its
            other half rather than as a column (#905). Centring the row means
            the column is centred alone and the pair is centred together. */}
        <div className="mx-auto flex w-fit max-w-full justify-center gap-10">
          {/*: The column narrows rather than being covered, so the list a
              reader was scanning is still beside what they opened. Wider than
              it was on both sides of that: at 52rem a two-clause headline wrapped
              to two lines with empty screen next to it. */}
          <main
            className={`min-w-0 flex-1 pb-40 pt-10 transition-[max-width] duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${
              open ? "max-w-[44rem]" : "max-w-[62rem]"
            }`}
          >
            {loading && <p className="py-24 text-center text-neutral-600">reading the window…</p>}

            {failed && (
              <p className="py-24 text-center font-mono text-[11px] uppercase tracking-[0.16em] text-red-400/80">
                the story API is unreachable
              </p>
            )}

            {!loading && !failed && (
              <>
                {pinned.length > 0 && (
                  <Section
                    label="Developing"
                    note="multi-day, still gathering coverage"
                  >
                    {pinned.map((ranked, i) => (
                      <StoryLine
                        key={ranked.story.id}
                        ranked={ranked}
                        rank={i + 1}
                        now={now}
                        active={openId === ranked.story.id}
                        onOpen={() => setOpenId(ranked.story.id)}
                      />
                    ))}
                  </Section>
                )}

                <Section
                  label="Ranked"
                  note={`last ${TOP_HOURS}h · independent owners, reach, freshness`}
                >
                  {rest.length === 0 ? (
                    <p className="py-10 text-neutral-600">
                      Nothing else in the window. An empty page is a finding, not an error.
                    </p>
                  ) : (
                    rest.map((ranked, i) => (
                      <StoryLine
                        key={ranked.story.id}
                        ranked={ranked}
                        rank={pinned.length + i + 1}
                        now={now}
                        active={openId === ranked.story.id}
                        onOpen={() => setOpenId(ranked.story.id)}
                      />
                    ))
                  )}
                </Section>

                <footer className="border-t border-neutral-800 py-8">
                  <Meta>
                    ranking is stated, not felt — every row shows the counts it was ranked on
                  </Meta>
                </footer>
              </>
            )}
          </main>

          {open && (
            <aside className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-[38rem] shrink-0 overflow-y-auto pb-40 pt-10 lg:block">
              <StoryReader storyId={openId} now={now} onClose={() => setOpenId(null)} />
            </aside>
          )}
        </div>
      </div>

      {/*: Below the breakpoint there is no room beside the column, so the
          reader takes the screen instead of squeezing both. */}
      {open && (
        <div className="fixed inset-0 z-30 overflow-y-auto bg-neutral-950 px-6 pb-40 pt-8 lg:hidden">
          <StoryReader storyId={openId} now={now} onClose={() => setOpenId(null)} />
        </div>
      )}

      {/*: Above the reader on purpose (z-40 over z-30): a question about the
          story you have open is the ordinary case, so the composer must not be
          the thing that opening a story buries. */}
      <AskDock onOpenStory={setOpenId} />
    </div>
  )
}
