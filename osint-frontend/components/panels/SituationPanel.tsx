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
import {
  fetchBrainAsk,
  fetchBrainNarrative,
  streamBrainAsk,
  type BrainSource,
} from "@/lib/apiClient"
import { fetchTopStories, type StoryRow } from "@/lib/analytics"
import { useStoryDetailStore } from "@/stores/storyDetailStore"
import {
  askHistory,
  chatReducer,
  dayMarkers,
  parseChatStorage,
  sortByActivity,
  splitRecent,
  type ChatMessage,
} from "@/lib/situation"

const NARRATIVE_REFRESH_MS = 5 * 60_000
const STORIES_REFRESH_MS = 60_000
//: Older than this and the card says the brain is resting.
const STALE_MS = 40 * 60_000
const CHAT_STORAGE_KEY = "brain-chat-v1"
//: Within this many px of the bottom still counts as "pinned" for auto-scroll.
const PIN_THRESHOLD_PX = 40

function TagChip({ category, escalating }: { category: string | null; escalating: string | null }) {
  if (!category) return null
  return (
    <span className="shrink-0 rounded border border-neutral-700 px-1 py-0.5 font-mono text-[9px] uppercase tracking-wide text-neutral-400">
      {category}
      {escalating === "yes" ? " ↑" : ""}
    </span>
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
    <div className="py-1">
      <button onClick={onOpen} className="flex w-full items-baseline gap-2 text-left">
        <span className="shrink-0 font-mono text-[10px] text-neutral-600">{n}</span>
        <span className="shrink-0 font-mono text-[10px] text-neutral-500">{time}</span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-neutral-300">{story.title}</span>
        <TagChip category={story.category} escalating={story.escalating} />
      </button>
    </div>
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
      const { answer, sources, closest_matches } = await streamBrainAsk(
        question,
        {
          onDelta: (text) => dispatch({ type: "delta", text }),
          onSources: (sources) => dispatch({ type: "sources", sources }),
        },
        history,
      )
      dispatch({ type: "finalize", answer, sources, closest: closest_matches ?? [] })
    } catch {
      try {
        const { answer, sources, closest_matches } = await fetchBrainAsk(question, history)
        dispatch({ type: "finalize", answer, sources, closest: closest_matches ?? [] })
      } catch {
        dispatch({ type: "fail" })
      }
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

function ChatEntry({ m }: { m: ChatMessage }) {
  return (
    <div className="py-2 text-sm">
      <p className="text-neutral-500">{m.question}</p>
      <p
        className={
          // whitespace-pre-line keeps the answer's paragraph breaks and
          // pointer lines (#484) — a plain <p> collapsed them into a wall.
          m.draft
            ? "whitespace-pre-line italic text-neutral-400"
            : "whitespace-pre-line text-neutral-200"
        }
      >
        {m.answer || "…"}
      </p>
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
  const openStory = useStoryDetailStore((s) => s.openStory)
  const [showOlder, setShowOlder] = useState(false)
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

  const narrative = data?.payload ?? null
  const createdAt = data?.created_at ? new Date(data.created_at).getTime() : 0
  const stale = !data?.present || Date.now() - createdAt > STALE_MS
  const sorted = sortByActivity(stories ?? [])
  const { recent, older } = splitRecent(sorted)
  //: A quiet spell must not blank the card — with nothing recent, show all.
  const rows = showOlder || recent.length === 0 ? sorted : recent
  const hiddenCount = sorted.length - rows.length
  const markers = dayMarkers(rows)

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

        {narrative?.headline ? (
          <h2 className="mb-2 text-lg font-semibold leading-snug">{narrative.headline}</h2>
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
                <ChatEntry key={i} m={m} />
              ))}
            </div>
          </section>
        ) : null}
      </div>

      <footer className="shrink-0 border-t border-neutral-800 p-3">
        {narrative?.system ? (
          <p className="mb-2 text-[11px] leading-snug text-neutral-500">
            {narrative.system}
            {data?.created_at ? ` · ${new Date(data.created_at).toLocaleTimeString()}` : ""}
          </p>
        ) : null}
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
