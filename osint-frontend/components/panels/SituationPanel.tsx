"use client"

/**
 * The Situation card (v2, #417) — a live briefing. The brain's headline read on
 * top, then the loudest stories with their Phase-3 gists (numbered, click to
 * expand each story's outlet sources), and a FIXED footer that keeps the system
 * status line and the ask box visible while the story list scrolls above it.
 */

import { useState } from "react"
import useSWR from "swr"
import { fetchBrainAsk, fetchBrainNarrative } from "@/lib/apiClient"
import type { BrainSource } from "@/lib/apiClient"
import { fetchStoryMembers, fetchTopStories, type StoryRow } from "@/lib/analytics"

const NARRATIVE_REFRESH_MS = 5 * 60_000
const STORIES_REFRESH_MS = 60_000
//: Older than this and the card says the brain is resting.
const STALE_MS = 40 * 60_000
const FEATURED = 2
const LIST_MAX = 6

function TagChip({ category, escalating }: { category: string | null; escalating: string | null }) {
  if (!category) return null
  return (
    <span className="shrink-0 rounded border border-neutral-700 px-1 py-0.5 font-mono text-[9px] uppercase tracking-wide text-neutral-400">
      {category}
      {escalating === "yes" ? " ↑" : ""}
    </span>
  )
}

function StorySources({ storyId }: { storyId: string }) {
  const { data, error } = useSWR(["situation-members", storyId], () => fetchStoryMembers(storyId))
  if (error) return <p className="px-2 py-1 font-mono text-[10px] text-red-400">sources unavailable</p>
  if (!data) return <p className="px-2 py-1 font-mono text-[10px] text-neutral-500">loading…</p>
  return (
    <ul className="mt-2 border-l-2 border-neutral-800 pl-3">
      {data.map((m, i) => (
        <li key={i} className="py-0.5 text-[11px] leading-snug text-neutral-400">
          <span className="font-mono text-[9px] uppercase tracking-wide text-cyan-300/70">{m.outlet}</span>{" "}
          {m.title}
        </li>
      ))}
    </ul>
  )
}

function FeaturedStory({
  n,
  story,
  expanded,
  onToggle,
}: {
  n: number
  story: StoryRow
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
      <button onClick={onToggle} className="flex w-full items-start gap-2 text-left">
        <span className="mt-0.5 shrink-0 font-mono text-xs text-neutral-500">{n}</span>
        <span className="min-w-0 flex-1">
          <span className="flex items-start justify-between gap-2">
            <span className="text-sm font-semibold leading-snug text-neutral-100">{story.title}</span>
            <TagChip category={story.category} escalating={story.escalating} />
          </span>
          {story.gist ? (
            <span className="mt-1 block text-[12px] leading-snug text-neutral-400">{story.gist}</span>
          ) : null}
        </span>
      </button>
      {expanded ? <StorySources storyId={story.id} /> : null}
    </div>
  )
}

function ListStory({
  n,
  story,
  expanded,
  onToggle,
}: {
  n: number
  story: StoryRow
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div className="py-1">
      <button onClick={onToggle} className="flex w-full items-baseline gap-2 text-left">
        <span className="shrink-0 font-mono text-[10px] text-neutral-600">{n}</span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-neutral-300">{story.title}</span>
        <TagChip category={story.category} escalating={story.escalating} />
      </button>
      {expanded ? <StorySources storyId={story.id} /> : null}
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
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (id: string) =>
    setExpanded((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const narrative = data?.payload ?? null
  const createdAt = data?.created_at ? new Date(data.created_at).getTime() : 0
  const stale = !data?.present || Date.now() - createdAt > STALE_MS
  const rows = stories ?? []
  const featured = rows.slice(0, FEATURED)
  const list = rows.slice(FEATURED, FEATURED + LIST_MAX)

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

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 pb-3">
        {stale ? (
          <p className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3 text-sm text-neutral-400">
            Brain resting — the box is busy or no read is ready yet.
            {data?.created_at ? ` Last read ${new Date(data.created_at).toLocaleTimeString()}.` : ""}
          </p>
        ) : null}

        {narrative?.headline ? (
          <h2 className="text-lg font-semibold leading-snug">{narrative.headline}</h2>
        ) : null}

        {featured.map((s, i) => (
          <FeaturedStory
            key={s.id}
            n={i + 1}
            story={s}
            expanded={expanded.has(s.id)}
            onToggle={() => toggle(s.id)}
          />
        ))}

        {list.length > 0 ? (
          <div className="flex flex-col divide-y divide-neutral-800/60">
            {list.map((s, i) => (
              <ListStory
                key={s.id}
                n={FEATURED + i + 1}
                story={s}
                expanded={expanded.has(s.id)}
                onToggle={() => toggle(s.id)}
              />
            ))}
          </div>
        ) : null}

        {rows.length === 0 && !narrative ? (
          <p className="text-sm text-neutral-500">No stories in the window yet.</p>
        ) : null}
      </div>

      <footer className="shrink-0 border-t border-neutral-800 p-3">
        {narrative?.system ? (
          <p className="mb-2 text-[11px] leading-snug text-neutral-500">
            {narrative.system}
            {data?.created_at ? ` · ${new Date(data.created_at).toLocaleTimeString()}` : ""}
          </p>
        ) : null}
        <AskBox />
      </footer>
    </div>
  )
}

type QA = { question: string; answer: string; sources: BrainSource[] }

function AskBox() {
  const [question, setQuestion] = useState("")
  const [pending, setPending] = useState(false)
  const [last, setLast] = useState<QA | null>(null)

  const submit = async () => {
    const q = question.trim()
    if (!q || pending) return
    setPending(true)
    try {
      const { answer, sources } = await fetchBrainAsk(q)
      setLast({ question: q, answer, sources })
      setQuestion("")
    } catch {
      setLast({ question: q, answer: "The brain is offline right now.", sources: [] })
    } finally {
      setPending(false)
    }
  }

  return (
    <div>
      {last ? (
        <div className="mb-2 text-sm">
          <p className="text-neutral-500">{last.question}</p>
          <p className="text-neutral-200">{last.answer}</p>
          {last.sources.length > 0 ? (
            <p className="mt-1 text-[11px] leading-snug text-neutral-500">
              sources:{" "}
              {last.sources.map((s) => (
                <span key={s.n}>
                  [{s.n}] {s.outlets.join(", ") || s.title}
                  {s.contested ? " ⚠" : ""}
                  {s.n < last.sources.length ? " · " : ""}
                </span>
              ))}
            </p>
          ) : null}
        </div>
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
    </div>
  )
}
