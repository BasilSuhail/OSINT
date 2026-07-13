"use client"

/**
 * The Situation card (#409) — the brain's plain-English read on the world
 * signal and the system's own health. Refreshes every 5 min; renders a
 * visible "resting" state when the brain has backed off (no narrative, or a
 * stale one) so backoff is honest, never hidden.
 */

import { useState } from "react"
import useSWR from "swr"
import { fetchBrainAsk, fetchBrainNarrative } from "@/lib/apiClient"

const REFRESH_MS = 5 * 60_000
//: Older than this and the card says the brain is resting.
const STALE_MS = 40 * 60_000

export function SituationPanel() {
  const { data } = useSWR("brain-narrative", fetchBrainNarrative, {
    refreshInterval: REFRESH_MS,
  })

  const narrative = data?.payload ?? null
  const createdAt = data?.created_at ? new Date(data.created_at).getTime() : 0
  const stale = !data?.present || Date.now() - createdAt > STALE_MS

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3 text-neutral-100">
      <header className="flex items-center justify-between">
        <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
          situation — the brain
        </p>
        {data?.model ? (
          <span className="font-mono text-[9px] text-neutral-600">{data.model}</span>
        ) : null}
      </header>

      {stale ? (
        <p className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3 text-sm text-neutral-400">
          Brain resting — the box is busy or no read is ready yet. Last narrative
          {data?.created_at ? ` from ${new Date(data.created_at).toLocaleTimeString()}` : " unavailable"}.
        </p>
      ) : null}

      {narrative ? (
        <>
          <h2 className="text-lg font-semibold leading-snug">{narrative.headline}</h2>
          {narrative.world ? <p className="text-sm text-neutral-300">{narrative.world}</p> : null}
          {narrative.system ? (
            <p className="text-sm text-neutral-400">{narrative.system}</p>
          ) : null}
          {narrative.watch && narrative.watch.length > 0 ? (
            <ul className="list-disc pl-5 text-sm text-neutral-300">
              {narrative.watch.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}

      <AskBox />
    </div>
  )
}

type QA = { question: string; answer: string }

function AskBox() {
  const [question, setQuestion] = useState("")
  const [pending, setPending] = useState(false)
  const [history, setHistory] = useState<QA[]>([])

  const submit = async () => {
    const q = question.trim()
    if (!q || pending) return
    setPending(true)
    try {
      const { answer } = await fetchBrainAsk(q)
      setHistory((h) => [{ question: q, answer }, ...h].slice(0, 5))
      setQuestion("")
    } catch {
      setHistory((h) => [{ question: q, answer: "The brain is offline right now." }, ...h].slice(0, 5))
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="mt-auto border-t border-neutral-800 pt-3">
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
      {history.length > 0 ? (
        <ul className="mt-3 flex flex-col gap-2">
          {history.map((qa, i) => (
            <li key={`${i}-${qa.question}`} className="text-sm">
              <p className="text-neutral-500">{qa.question}</p>
              <p className="text-neutral-200">{qa.answer}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
