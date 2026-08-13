"use client"

/**
 * The reading page's question box (#905).
 *
 * The console keeps its composer at the foot of the Situation panel, always
 * under the stories, so asking is never a navigation. The reading page had no
 * composer at all — the only way to ask about a story you were reading was to
 * leave the page you were reading it on.
 *
 * Docked to the bottom of the viewport rather than placed at the end of the
 * column: the column is a scroll of sixty stories, and a composer at the
 * bottom of it is a composer you have to reach. This one is where a chat's is,
 * because that is the gesture people already have for "ask something about
 * this".
 *
 * The transcript grows upward from the input, capped so it can never take the
 * page it is asking about, and the ask itself is the console's own
 * `useBrainChat` — same stream, same citations, same transcript in
 * sessionStorage. Nothing about the conversation is re-implemented here; this
 * file is furniture.
 */

import { useEffect, useRef, useState } from "react"
import { ChatEntry, useBrainChat } from "@/components/panels/SituationPanel"

//: Within this many px of the bottom still counts as "pinned" for auto-scroll.
const PIN_THRESHOLD_PX = 40

export function AskDock({ onOpenStory }: { onOpenStory: (id: string) => void }) {
  const { messages, pending, ask, clear } = useBrainChat()
  const [question, setQuestion] = useState("")

  const scrollRef = useRef<HTMLDivElement>(null)
  //: Only auto-scroll while the reader sits at the bottom, so a streaming
  //: answer never hijacks a scroll back up to something they were re-reading.
  const pinnedRef = useRef(true)

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

  //: The chip's shortcut (#602): "elaborate" is the word the backend detects to
  //: switch into long-answer mode, so the chip needs no endpoint of its own.
  const elaborate = () => {
    if (pending) return
    pinnedRef.current = true
    void ask("elaborate on that")
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 px-6 pb-5">
      {/*: Narrower than the column and see-through: it floats over the news it
          is asking about, and a solid bar the full width of the page reads as
          a second page rather than as a thing resting on this one (#911). */}
      <div className="pointer-events-auto mx-auto w-full max-w-[42rem] rounded-xl border border-neutral-700/40 bg-neutral-950/55 shadow-xl shadow-black/40 backdrop-blur-2xl">
        {messages.length > 0 && (
          <div className="border-b border-neutral-800/80">
            <div className="flex items-baseline justify-between px-3 pt-2">
              <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
                ask — transcript
              </p>
              <button
                onClick={clear}
                className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500 transition-colors hover:text-neutral-300"
              >
                clear
              </button>
            </div>
            {/*: Capped: the answer must never take the page it is answering
                about. Past the cap it scrolls, and the input stays put. */}
            <div
              ref={scrollRef}
              onScroll={onScroll}
              className="max-h-[38vh] overflow-y-auto px-3 pb-2"
            >
              <div className="divide-y divide-neutral-800/60">
                {messages.map((m, i) => (
                  <ChatEntry
                    key={i}
                    m={m}
                    onOpenStory={onOpenStory}
                    //: Only the latest finalized answer gets the chip —
                    //: retrieval anchors on the most recent exchange, so
                    //: elaborating an older one would drift topic (#602).
                    onElaborate={
                      i === messages.length - 1 && !m.draft && !pending ? elaborate : undefined
                    }
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="p-2">
          <div className="flex gap-2">
            <input
              //: Named for the same reason the omnibox is (#944): a field
              //: with neither attribute cannot be told apart for autofill,
              //: and this one wants none of it.
              id="ask-dock-question"
              name="ask-dock-question"
              autoComplete="off"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit()
              }}
              placeholder="ask the brain…"
              disabled={pending}
              aria-label="Ask the brain"
              className="flex-1 rounded-lg border border-neutral-700/40 bg-neutral-900/40 px-3 py-1.5 text-[0.875rem] text-neutral-100 placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none disabled:opacity-50"
            />
            <button
              onClick={submit}
              disabled={pending || !question.trim()}
              className="rounded-lg border border-neutral-700/40 px-3.5 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-400 transition-colors hover:border-neutral-600 hover:text-neutral-100 disabled:opacity-40"
            >
              {pending ? "…" : "ask"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
