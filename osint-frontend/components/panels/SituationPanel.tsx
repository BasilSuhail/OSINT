"use client"

/**
 * The Situation card (v3, #439) — a live feed. The brain's headline read on top,
 * then every story in the window ordered by latest activity (newest first, so
 * fresh news pushes older rows down), then the ask transcript — one continuous
 * scroll surface. The system status line and the ask box sit in a FIXED footer
 * below it; sending a question pins the scroll to the transcript end.
 */

import { useEffect, useReducer, useRef, useState } from "react"
import useSWR from "swr"
import { fetchBrainNarrative, streamBrainAsk, type BrainSource } from "@/lib/apiClient"
import {
  fetchAuditLatest,
  fetchContestedStories,
  fetchDevelopingStories,
  fetchTopStories,
  type AuditLatest,
  type ContestedStory,
  type DevelopingStory,
  type StoryRow,
} from "@/lib/analytics"
import { useStoryDetailStore } from "@/stores/storyDetailStore"
import { ListRow, TagChip } from "../ListRow"
import {
  answerLines,
  askHistory,
  chatReducer,
  dayMarkers,
  excludePinned,
  filterStoriesByCategory,
  parseChatStorage,
  sortStories,
  storyCategories,
  splitRecent,
  STORY_SORTS,
  type StorySort,
  type ChatMessage,
} from "@/lib/situation"

const NARRATIVE_REFRESH_MS = 5 * 60_000
const STORIES_REFRESH_MS = 60_000
//: The audit runs once a night, so anything faster is polling for nothing.
const AUDIT_REFRESH_MS = 15 * 60_000
//: Shown at a glance; the rest fold away behind a count (#695).
const DEVELOPING_COLLAPSED = 3
//: Fetched, so "show more" reveals rather than waits on a request. Ten is the
//: ceiling /stories/developing enforces (api.py: `le=10`); asking for twelve
//: 422'd every request and the block silently rendered nothing (#713).
const DEVELOPING_FETCH = 10
//: Older than this and the card says the brain is resting.
const STALE_MS = 40 * 60_000
const CHAT_STORAGE_KEY = "brain-chat-v1"
//: Within this many px of the bottom still counts as "pinned" for auto-scroll.
const PIN_THRESHOLD_PX = 40

/**
 * Order and category for the feed below.
 *
 * Two rows of chips rather than dropdowns: the whole point is that the reader
 * can see what the list is doing without opening anything, and a closed select
 * hides its own state. The count on the right is the honest part — it says how
 * many of the window's stories the current choice is showing.
 */
function FeedControls({
  sort,
  onSort,
  categories,
  category,
  onCategory,
  showing,
  total,
}: {
  sort: StorySort
  onSort: (mode: StorySort) => void
  categories: string[]
  category: string | null
  onCategory: (category: string | null) => void
  showing: number
  total: number
}) {
  if (total === 0) return null
  const chip = (on: boolean) =>
    `rounded-md px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide transition-colors ${
      on
        ? "bg-neutral-800 text-neutral-100"
        : "text-neutral-500 hover:bg-neutral-900 hover:text-neutral-300"
    }`
  return (
    <div className="mb-2 flex flex-col gap-1 border-b border-neutral-800 pb-2">
      <div className="flex items-center gap-1">
        <span className="mr-0.5 font-mono text-[9px] uppercase tracking-wide text-neutral-600">
          sort
        </span>
        {STORY_SORTS.map((option) => (
          <button
            key={option.key}
            type="button"
            title={option.hint}
            aria-pressed={sort === option.key}
            onClick={() => onSort(option.key)}
            className={chip(sort === option.key)}
          >
            {option.label}
          </button>
        ))}
        <span className="ml-auto font-mono text-[9px] tabular-nums text-neutral-600">
          {showing === total ? `${total}` : `${showing}/${total}`}
        </span>
      </div>
      {categories.length > 1 ? (
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-0.5 font-mono text-[9px] uppercase tracking-wide text-neutral-600">
            show
          </span>
          <button
            type="button"
            aria-pressed={category === null}
            onClick={() => onCategory(null)}
            className={chip(category === null)}
          >
            all
          </button>
          {categories.map((name) => (
            <button
              key={name}
              type="button"
              aria-pressed={category === name}
              onClick={() => onCategory(category === name ? null : name)}
              className={chip(category === name)}
            >
              {name}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

/**
 * The pinned slot (#449): multi-day international stories still gathering
 * coverage. Nothing qualifying → nothing rendered, because an empty slot is
 * itself the finding. Corroboration shows on the row and never gates the pin.
 */
function DevelopingBlock({
  stories,
  failed,
  onOpen,
}: {
  stories: DevelopingStory[]
  failed: boolean
  onOpen: (id: string) => void
}) {
  //: Three is the glance; the rest are fetched and folded away (#695). The pin
  //: query already ranks them, so "more" is genuinely more of the same thing
  //: rather than a different, looser list.
  const [showAll, setShowAll] = useState(false)
  //: Silence means "nothing qualifies", which is itself the finding. It must
  //: not also mean "the request failed" — those looked identical on screen for
  //: as long as the fetch was 422ing (#713).
  if (failed) {
    return (
      <div className="mb-2 border-b border-neutral-800 pb-2 font-mono text-[9px] uppercase tracking-widest text-red-400/80">
        developing — unavailable
      </div>
    )
  }
  if (stories.length === 0) return null
  const visible = showAll ? stories : stories.slice(0, DEVELOPING_COLLAPSED)
  const hidden = stories.length - visible.length
  return (
    <div className="mb-2 border-b border-neutral-800 pb-2">
      <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-amber-500/80">
        developing
      </div>
      {visible.map((s) => (
        <button
          key={s.id}
          onClick={() => onOpen(s.id)}
          className="mb-1 block w-full text-left"
        >
          <div className="flex items-baseline gap-2">
            <span className="shrink-0 text-amber-500/80">●</span>
            <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-neutral-100">
              {s.title}
            </span>
          </div>
          <div className="pl-4 font-mono text-[9px] text-neutral-500">
            {s.outlet_count} outlets · {s.pin_reasons.countries} countries ·{" "}
            {s.pin_reasons.age_hours}h ·{" "}
            {s.corroboration === null
              ? "unscored"
              : `corrob ${s.corroboration.toFixed(2)}`}{" "}
            · {s.owner_count} owners
          </div>
        </button>
      ))}
      {stories.length > DEVELOPING_COLLAPSED ? (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="font-mono text-[9px] uppercase tracking-widest text-amber-600/70 hover:text-amber-400"
        >
          {showAll ? "− fewer" : `+ ${hidden} more developing`}
        </button>
      ) : null}
    </div>
  )
}

function StoryLine({
  n,
  story,
  onOpen,
}: {
  n: number
  story: StoryRow
  onOpen: () => void
}) {
  const time = new Date(story.last_seen).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })
  return (
    <ListRow
      n={n}
      time={time}
      timestamp={story.last_seen}
      title={story.title}
      trailing={<TagChip category={story.category} escalating={story.escalating} />}
      onOpen={onOpen}
    />
  )
}

/** Transcript state + ask flow, persisted per-tab in sessionStorage (#439). */
function useBrainChat() {
  const [messages, dispatch] = useReducer(chatReducer, [])
  const [pending, setPending] = useState(false)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    const restored = parseChatStorage(sessionStorage.getItem(CHAT_STORAGE_KEY))
    if (restored.length > 0) dispatch({ type: "restore", messages: restored })
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (!hydrated) return
    sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages))
  }, [messages, hydrated])

  const ask = async (question: string) => {
    //: Snapshot before the new draft joins the transcript (#444).
    const history = askHistory(messages)
    dispatch({ type: "ask", question })
    setPending(true)
    try {
      const { answer, sources, closest_matches, claims, reasoning } = await streamBrainAsk(
        question,
        {
          onDelta: (text) => dispatch({ type: "delta", text }),
          onSources: (sources) => dispatch({ type: "sources", sources }),
        },
        history,
      )
      dispatch({
        type: "finalize",
        answer,
        sources,
        closest: closest_matches ?? [],
        claims: claims ?? [],
        reasoning: reasoning ?? null,
      })
    } catch {
      //: No second attempt here. The stream already falls back to the
      //: non-streamed endpoint when the response carries no body, which is the
      //: case this branch was covering; reaching it now means the ask itself
      //: failed, and asking again only spends another full generation to fail
      //: the same way while the reader waits through both.
      dispatch({ type: "fail" })
    } finally {
      setPending(false)
    }
  }

  const clear = () => dispatch({ type: "clear" })

  return { messages, pending, ask, clear }
}

function sourceSpans(items: BrainSource[]) {
  return items.map((s, i) => (
    <span key={s.n}>
      [{s.n}] {s.outlets.join(", ") || s.title}
      {s.contested ? " ⚠" : ""}
      {i < items.length - 1 ? " · " : ""}
    </span>
  ))
}

const CHIP_BASE =
  "mx-0.5 align-baseline text-[11px] underline decoration-dotted underline-offset-2"

function ChatEntry({
  m,
  onOpenStory,
  onElaborate,
}: {
  m: ChatMessage
  onOpenStory: (id: string) => void
  //: Present only on the latest finalized answer (#602): tapping it asks the
  //: brain to elaborate on that answer — a shortcut for typing "elaborate".
  onElaborate?: () => void
}) {
  //: Which (thinking) chip's analysis panel is open, by claim index (#476).
  const [openThinking, setOpenThinking] = useState<number | null>(null)
  const storyFor = (n: number) =>
    m.sources.find((s) => s.n === n) ?? m.closest.find((s) => s.n === n)
  return (
    <div className="py-2 text-sm">
      <p className="text-neutral-500">{m.question}</p>
      {m.draft ? (
        // whitespace-pre-line keeps paragraph breaks (#484); chips arrive with
        // the verified final, never on the unchecked draft.
        <p className="whitespace-pre-line italic text-neutral-400">{m.answer || "…"}</p>
      ) : (
        <div className="text-neutral-200">
          {answerLines(m.answer, m.claims).map((segments, i) =>
            segments.length === 0 ? (
              <div key={i} className="h-2" />
            ) : (
              <p key={i} className="leading-relaxed">
                {segments.map((seg, j) => {
                  if (seg.type === "text") return <span key={j}>{seg.text}</span>
                  if (seg.type === "source") {
                    const story = storyFor(seg.n)
                    return (
                      <button
                        key={j}
                        onClick={
                          story && story.story_id !== null
                            ? () => onOpenStory(String(story.story_id))
                            : undefined
                        }
                        title={story ? story.outlets.join(", ") || story.title : undefined}
                        className={`${CHIP_BASE} text-sky-300/80 hover:text-sky-200`}
                      >
                        (source)
                      </button>
                    )
                  }
                  return (
                    <button
                      key={j}
                      onClick={() =>
                        setOpenThinking(openThinking === seg.claim ? null : seg.claim)
                      }
                      className={`${CHIP_BASE} italic text-neutral-500 hover:text-neutral-300`}
                    >
                      (thinking)
                    </button>
                  )
                })}
              </p>
            ),
          )}
        </div>
      )}
      {openThinking !== null && m.claims[openThinking] ? (
        <div className="mt-1 rounded-lg border border-neutral-800 bg-neutral-900/60 p-2 text-[11px] leading-snug">
          <p className="mb-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
            the brain&apos;s own analysis — no local story directly backs this sentence
          </p>
          <p className="text-neutral-300">{m.claims[openThinking].text}</p>
          {m.reasoning ? (
            <p className="mt-1 text-neutral-500">
              retrieval: {m.reasoning.method ?? "—"}
              {m.reasoning.intents.length > 0
                ? ` · intents: ${m.reasoning.intents.join(", ")}`
                : ""}
              {m.reasoning.terms.length > 0 ? ` · terms: ${m.reasoning.terms.join(", ")}` : ""}
            </p>
          ) : null}
        </div>
      ) : null}
      {m.draft && m.answer ? (
        <p className="mt-0.5 text-[10px] uppercase tracking-wide text-neutral-600">
          drafting — verifying sources…
        </p>
      ) : null}
      {m.sources.length > 0 ? (
        <p className="mt-1 text-[11px] leading-snug text-neutral-500">
          sources: {sourceSpans(m.sources)}
        </p>
      ) : null}
      {m.closest.length > 0 ? (
        <p className="mt-1 text-[11px] leading-snug text-neutral-600">
          closest matches — not evidence: {sourceSpans(m.closest)}
        </p>
      ) : null}
      {onElaborate ? (
        <button
          onClick={onElaborate}
          className="mt-1.5 rounded-md border border-neutral-800 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-neutral-500 hover:text-neutral-300"
        >
          elaborate ⌄
        </button>
      ) : null}
    </div>
  )
}


/**
 * Data-quality line (#692). The nightly source-data audit (#669) had a history
 * and no reader, so the check that found `fred` and `polymarket` contributing
 * nothing to the composite was visible only in psql.
 *
 * Deliberately a line, not a panel: this reports health, it does not analyse.
 * Silent when the audit has never completed — an empty frame reading "0
 * findings" would be a clean bill of health the system has not earned.
 */
function DataQualityLine({ audit }: { audit: AuditLatest | undefined }) {
  const [open, setOpen] = useState(false)
  if (!audit || !audit.present || audit.findings_total === null) return null

  const total = audit.findings_total
  const delta = audit.delta
  const worse = delta !== null && delta > 0

  return (
    <div className="mb-2 font-mono text-[10px]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-baseline gap-2 text-left text-neutral-500 hover:text-neutral-300"
      >
        <span className="uppercase tracking-widest text-neutral-600">data quality</span>
        <span className={total === 0 ? "text-emerald-500" : "text-amber-500"}>
          {total} finding{total === 1 ? "" : "s"}
        </span>
        {audit.sources_measured !== null ? (
          <span className="text-neutral-600">/ {audit.sources_measured} sources</span>
        ) : null}
        {delta !== null && delta !== 0 ? (
          <span className={worse ? "text-red-400" : "text-emerald-500"}>
            {worse ? "▲" : "▼"}
            {Math.abs(delta)}
          </span>
        ) : null}
        {delta === null ? <span className="text-neutral-600">first run</span> : null}
        <span className="ml-auto text-neutral-700">{open ? "−" : "+"}</span>
      </button>
      {open ? (
        <ul className="mt-1 space-y-0.5 border-l border-neutral-800 pl-2">
          {audit.findings.map((f) => (
            <li key={`${f.source}:${f.check}`} className="text-neutral-500">
              <span className="text-neutral-300">{f.source}</span>{" "}
              <span className="text-amber-600/80">{f.check}</span>
              <div className="pl-2 text-[9px] text-neutral-600">{f.detail}</div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}


/**
 * Most contested telling (#695) — the one block worth rescuing from the
 * briefing card before it was folded away.
 *
 * Divergence 0 means the blocs word the story identically; 1 means they share
 * nothing. It sits next to developing because the pair answers the question the
 * card is for: what is growing, and what is being told two different ways.
 */
function ContestedBlock({
  story,
  onOpen,
}: {
  story: ContestedStory | undefined
  onOpen: (id: string) => void
}) {
  if (!story) return null
  const blocs = Object.keys(story.groups ?? {})
  return (
    <div className="mb-2 border-b border-neutral-800 pb-2">
      <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-cyan-500/80">
        most contested
      </div>
      <button onClick={() => onOpen(story.story_id)} className="block w-full text-left">
        <div className="flex items-baseline gap-2">
          <span className="shrink-0 font-mono text-[10px] text-cyan-400">
            {story.divergence.toFixed(2)}
          </span>
          <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-neutral-100">
            {story.title}
          </span>
        </div>
        {blocs.length ? (
          <div className="pl-4 font-mono text-[9px] text-neutral-500">
            {blocs.join(" vs ")}
          </div>
        ) : null}
      </button>
    </div>
  )
}

export function SituationPanel() {
  const { data } = useSWR("brain-narrative", fetchBrainNarrative, {
    refreshInterval: NARRATIVE_REFRESH_MS,
  })
  const { data: stories } = useSWR("situation-stories", () => fetchTopStories(72, 50), {
    refreshInterval: STORIES_REFRESH_MS,
  })
  const { data: pinned, error: pinnedError } = useSWR(
    "stories-developing",
    () => fetchDevelopingStories(DEVELOPING_FETCH),
    { refreshInterval: STORIES_REFRESH_MS },
  )
  // The audit runs nightly, so polling it hard would be noise.
  const { data: audit } = useSWR("audit-latest", fetchAuditLatest, {
    refreshInterval: AUDIT_REFRESH_MS,
  })
  const { data: contested } = useSWR("situation-contested", fetchContestedStories, {
    refreshInterval: STORIES_REFRESH_MS,
  })
  const openStory = useStoryDetailStore((s) => s.openStory)
  const [showOlder, setShowOlder] = useState(false)
  //: Session state, not a stored preference: the card opens on the live order
  //: every time, and a reader who changed it did so for the question they had.
  const [sort, setSort] = useState<StorySort>("activity")
  const [category, setCategory] = useState<string | null>(null)
  const [question, setQuestion] = useState("")
  const { messages, pending, ask, clear } = useBrainChat()
  const scrollRef = useRef<HTMLDivElement>(null)
  //: Only auto-scroll while the user sits at the bottom, so streaming never
  //: hijacks a scroll back up to the story list.
  const pinnedRef = useRef(false)

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < PIN_THRESHOLD_PX
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight
  }, [messages])

  const submit = () => {
    const q = question.trim()
    if (!q || pending) return
    setQuestion("")
    pinnedRef.current = true
    void ask(q)
  }

  //: The chip's shortcut (#602): the "elaborate" trigger word is what the
  //: backend detects to switch into long-answer mode — no special API needed.
  const elaborate = () => {
    if (pending) return
    pinnedRef.current = true
    void ask("elaborate on that")
  }

  const narrative = data?.payload ?? null
  const createdAt = data?.created_at ? new Date(data.created_at).getTime() : 0
  const stale = !data?.present || Date.now() - createdAt > STALE_MS
  const developing = pinned ?? []
  //: Order and category are the reader's, not the card's. The feed's own
  //: order (newest first) stays the default because a surface being watched
  //: should move when the world does; the other orders answer questions
  //: recency cannot, and every one of them is checkable against the row.
  const unpinned = excludePinned(stories ?? [], developing.map((s) => s.id))
  const categories = storyCategories(unpinned)
  //: A category that stops appearing must not leave the feed empty and
  //: unexplained — the chip goes, so the filter goes with it.
  const activeCategory = category !== null && categories.includes(category) ? category : null
  const sorted = sortStories(filterStoriesByCategory(unpinned, activeCategory), sort)
  //: Day markers only mean anything while the list is in day order.
  const { recent, older } =
    sort === "activity" ? splitRecent(sorted) : { recent: sorted, older: [] as typeof sorted }
  //: A quiet spell must not blank the card — with nothing recent, show all.
  const rows = showOlder || recent.length === 0 ? sorted : recent
  const hiddenCount = sorted.length - rows.length
  const markers = sort === "activity" ? dayMarkers(rows) : rows.map(() => null)

  return (
    <div className="flex h-full flex-col text-neutral-100">
      <header className="flex items-center justify-between p-3 pb-2">
        <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
          situation — the brain
        </p>
        {data?.model ? (
          <span className="font-mono text-[9px] text-neutral-600">{data.model}</span>
        ) : null}
      </header>

      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {stale ? (
          <p className="mb-3 rounded-xl border border-neutral-800 bg-neutral-900/50 p-3 text-sm text-neutral-400">
            Brain resting — the box is busy or no read is ready yet.
            {data?.created_at ? ` Last read ${new Date(data.created_at).toLocaleTimeString()}.` : ""}
          </p>
        ) : null}

        <DevelopingBlock
          stories={developing}
          failed={Boolean(pinnedError)}
          onOpen={openStory}
        />
        <ContestedBlock story={(contested ?? [])[0]} onOpen={openStory} />

        <FeedControls
          sort={sort}
          onSort={setSort}
          categories={categories}
          category={activeCategory}
          onCategory={setCategory}
          showing={rows.length}
          total={unpinned.length}
        />

        {/*: A filter that empties the list says so, and says how to undo it.
            A silent empty feed reads as a broken card. */}
        {rows.length === 0 && unpinned.length > 0 ? (
          <button
            onClick={() => setCategory(null)}
            className="w-full rounded-lg border border-neutral-800 py-2 font-mono text-[10px] uppercase tracking-wide text-neutral-500 hover:text-neutral-300"
          >
            no {activeCategory} stories in this window — show all
          </button>
        ) : null}

        {rows.length > 0 ? (
          <div className="flex flex-col divide-y divide-neutral-800/60">
            {rows.map((s, i) => (
              <div key={s.id}>
                {markers[i] ? (
                  <p className="pt-2 font-mono text-[9px] uppercase tracking-wide text-neutral-600">
                    {markers[i]}
                  </p>
                ) : null}
                <StoryLine n={i + 1} story={s} onOpen={() => openStory(s.id)} />
              </div>
            ))}
          </div>
        ) : null}

        {hiddenCount > 0 ? (
          <button
            onClick={() => setShowOlder(true)}
            className="mt-2 w-full rounded-lg border border-neutral-800 py-1.5 font-mono text-[10px] uppercase tracking-wide text-neutral-500 hover:text-neutral-300"
          >
            + {hiddenCount} older stories
          </button>
        ) : null}
        {showOlder && older.length > 0 && recent.length > 0 ? (
          <button
            onClick={() => setShowOlder(false)}
            className="mt-2 w-full rounded-lg border border-neutral-800 py-1.5 font-mono text-[10px] uppercase tracking-wide text-neutral-500 hover:text-neutral-300"
          >
            − hide older stories
          </button>
        ) : null}

        {rows.length === 0 && !narrative ? (
          <p className="text-sm text-neutral-500">No stories in the window yet.</p>
        ) : null}

        {messages.length > 0 ? (
          <section>
            <div className="sticky top-0 z-10 -mx-3 mt-3 flex items-center justify-between border-y border-neutral-800 bg-neutral-950/95 px-3 py-1 backdrop-blur">
              <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
                ask — transcript
              </p>
              <button
                onClick={clear}
                className="font-mono text-[9px] uppercase tracking-wide text-neutral-500 hover:text-neutral-300"
              >
                clear
              </button>
            </div>
            <div className="divide-y divide-neutral-800/60">
              {messages.map((m, i) => (
                <ChatEntry
                  key={i}
                  m={m}
                  onOpenStory={openStory}
                  //: Only the latest, finalized answer gets the chip — retrieval
                  //: anchors on the most recent exchange, so elaborating an older
                  //: one would drift topic (#602).
                  onElaborate={i === messages.length - 1 && !m.draft && !pending ? elaborate : undefined}
                />
              ))}
            </div>
          </section>
        ) : null}
      </div>

      <footer className="shrink-0 border-t border-neutral-800 p-3">
        <DataQualityLine audit={audit} />
        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit()
            }}
            placeholder="ask the brain…"
            disabled={pending}
            className="flex-1 rounded-lg border border-neutral-800 bg-neutral-900/50 px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-600 focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={submit}
            disabled={pending || !question.trim()}
            className="rounded-lg border border-neutral-700 px-3 py-2 text-sm text-neutral-300 disabled:opacity-40"
          >
            {pending ? "…" : "ask"}
          </button>
        </div>
      </footer>
    </div>
  )
}
