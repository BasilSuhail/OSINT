"use client"

/**
 * One box at the top of the console (#938).
 *
 * There used to be two. Search sat on the world card and asked the gazetteer
 * and the full-text index; the ask box sat in the situation card's footer and
 * asked the brain. "Flooding in Kerala" is a legitimate thing to type into
 * either of them, so before typing anything a reader first had to decide which
 * card held the box that would answer them, and then find that card. That is a
 * decision the console was making the reader take on its behalf.
 *
 * The merged box asks both, and the reader never chooses between them:
 * typing runs the cheap search on every pause, and the ask button — never a
 * guess about what the words meant — runs the expensive one. Both answers land
 * in the same dropdown, search above, the brain below.
 *
 * At the top of the left column rather than over the middle of the map: the
 * map keeps the centre, and everything the box finds opens underneath it in
 * the column the reader already looks at for written things. The bar is above
 * the deck rather than inside it, so it is never a page of a card that has to
 * be found first.
 *
 * The bar and the deck take turns in that column. A query pushes the deck out
 * of the way and the results take the space; clearing the query gives it back.
 * The bar itself never goes anywhere — hiding the left panel hides what is
 * under the bar, never the bar, because the way into the system is not a thing
 * a reader should be able to lose.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronDown, ChevronLeft, Search, X } from "lucide-react"

import { EventDetailCard } from "@/components/EventDetailCard"
import { ChatEntry, useBrainChat } from "@/components/panels/SituationPanel"
import { fetchSearch, type SearchPlace, type SearchResponse } from "@/lib/apiClient"
import { eventHeadline } from "@/lib/eventTitle"
import type { VisibleEvent } from "@/lib/queries"
import type { EventRow } from "@/lib/types"
import { colorForEvent } from "@/lib/types"
import { PANEL_WIDTH } from "@/lib/layout"
import { cn } from "@/lib/utils"
import { usePanelLayoutStore } from "@/stores/panelLayout"
import { usePlaceStore } from "@/stores/placeStore"
import { useStoryDetailStore } from "@/stores/storyDetailStore"

/** Below this a query is a keystroke, not a question. Matches the server. */
const MIN_QUERY = 2

/** Long enough that a fast typist issues one request per word rather than
 *  one per letter; short enough that a pause feels answered. */
const DEBOUNCE_MS = 180

/** How close the map gets. A city is a place you look at; a region is an area
 *  you survey, and dropping to street level inside one hides the thing that
 *  makes it a region. */
const ZOOM_BY_KIND: Record<SearchPlace["kind"], number> = {
  city: 9,
  region: 6,
  country: 4,
}

function flyTo(lat: number, lon: number, zoom: number): void {
  //: The map already listens for this (#699). A second channel would be a
  //: second thing to keep in step.
  window.dispatchEvent(new CustomEvent("osint:flyto", { detail: { lat, lon, zoom } }))
}

function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

/** Search reaches back thirty days; the map's fade only describes the live
 *  window. Rather than invent an age for a row that is outside it, hand the
 *  detail panel the row at full strength — it reads none of these fields, and
 *  a fabricated opacity would be a claim about recency that isn't true. */
function asVisible(ev: EventRow): VisibleEvent {
  return {
    ...ev,
    age: 0,
    opacity: 1,
    occurredMs: new Date(ev.occurred_at).getTime(),
    ongoing: false,
  }
}

interface OmniboxProps {
  /** Phone layout (#942): the bar spans the screen instead of a column, and
   *  its results stop short of the bottom rather than reaching it, because
   *  the sheet is down there. Passed rather than read from a store — which
   *  layout the box is in is a fact about where it was rendered, and a
   *  component that asks a store where it is can be rendered somewhere that
   *  disagrees. */
  narrow?: boolean
}

export function Omnibox({ narrow = false }: OmniboxProps) {
  const [query, setQuery] = useState("")
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  //: The row the reader opened. Kept here rather than in the pop-up store
  //: because the pop-up is the deck's second column: routing a search result
  //: through it makes the deck spring open around a card the reader asked
  //: search for, and puts that card under this bar (#938). Search answers in
  //: its own box or it does not answer here at all.
  const [detail, setDetail] = useState<VisibleEvent | null>(null)
  //: Focus counts as using the box. The deck steps out when the reader turns
  //: to search, not once they have typed enough characters for the server to
  //: answer — waiting for the query floor means the column sits there full of
  //: the thing they just turned away from.
  const [focused, setFocused] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const open = usePanelLayoutStore((s) => s.top)
  const setPanel = usePanelLayoutStore((s) => s.setPanel)
  const setSearchActive = usePanelLayoutStore((s) => s.setSearchActive)
  const openCountry = usePlaceStore((s) => s.openCountry)
  const openStory = useStoryDetailStore((s) => s.openStory)

  //: Same conversation the reading page runs. Kept mounted behind the collapse
  //: so putting the dropdown away never costs the transcript — that is the
  //: whole difference between minimising and clearing.
  const { messages, pending, ask, clear } = useBrainChat()

  const typed = query.trim().length >= MIN_QUERY
  /** Whether the reader is using this box: it has the cursor, or something is
   *  in it — a query, a row opened from a result, an answer.
   *
   *  This is what takes the column from the deck, so the panel below renders
   *  on exactly the same condition. The two must not disagree: hiding the deck
   *  on a condition the panel does not fill leaves an empty column with the
   *  collapse handle stranded beside nothing (#938).
   *
   *  Declared above the effects that read it: they list it as a dependency,
   *  which is evaluated while this function runs, not when the effect fires.
   */
  const searching = focused || query.trim().length > 0 || detail !== null || messages.length > 0

  const focusBar = useCallback(() => {
    setPanel("top", true)
    inputRef.current?.focus()
  }, [setPanel])

  /** Leaving search: the query goes, whatever it opened goes, and the deck
   *  comes back into the column. The one gesture behind both the cross and
   *  Escape — two ways out is fine, two different outcomes is not. */
  const clearSearch = useCallback(() => {
    abortRef.current?.abort()
    setQuery("")
    setResult(null)
    setDetail(null)
    setFailed(false)
    setFocused(false)
    //: The transcript too. It is in this panel and it is holding the column,
    //: so leaving search has to leave it — a cross that empties everything
    //: except the part still covering the deck has not done what it says.
    clear()
    inputRef.current?.blur()
  }, [clear])

  //: `/` and ⌘K are the two gestures people already have for "put the cursor
  //: in the search box". Neither steals a keystroke from a field they are
  //: already typing in.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault()
        focusBar()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [focusBar])

  //: Esc leaves search before anything else sees the press, and leaves it from
  //: inside the field as much as from outside it: the listener is on the
  //: window in the capture phase, so it runs before the input's own handling
  //: whether or not the cursor is sitting in the box. The reader gets the
  //: cursor back out, the query cleared and the deck returned in one press.
  //:
  //: Stopping propagation matters: the same key sends the deck home, and a
  //: reader leaving a search should get the deck back, not lose their place in
  //: it. Only while there is a search to leave — otherwise Esc belongs to
  //: whatever is on top, which is the pop-up.
  useEffect(() => {
    if (!searching) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      e.stopPropagation()
      //: The browser's own Escape-in-a-field behaviour is a revert, not an
      //: exit, and it would leave the cursor where it was.
      e.preventDefault()
      clearSearch()
    }
    window.addEventListener("keydown", onKey, { capture: true })
    return () => window.removeEventListener("keydown", onKey, { capture: true })
  }, [searching, clearSearch])

  //: The column can only hold one of the two, so it has to be said out loud
  //: where the layout can hear it.
  useEffect(() => {
    setSearchActive(searching)
  }, [searching, setSearchActive])

  useEffect(() => {
    const trimmed = query.trim()
    if (trimmed.length < MIN_QUERY) {
      abortRef.current?.abort()
      setResult(null)
      setBusy(false)
      setFailed(false)
      return
    }
    const timer = setTimeout(() => {
      //: Cancel the in-flight query before starting another. Otherwise a slow
      //: early response lands after a fast later one and overwrites it, so
      //: the reader sees results for a query they have already changed.
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      setBusy(true)
      setFailed(false)
      fetchSearch(trimmed, { signal: controller.signal })
        .then((r) => {
          if (!controller.signal.aborted) setResult(r)
        })
        .catch((err) => {
          if ((err as Error)?.name !== "AbortError") setFailed(true)
        })
        .finally(() => {
          if (!controller.signal.aborted) setBusy(false)
        })
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query])

  const submitAsk = () => {
    const q = query.trim()
    if (!q || pending) return
    setPanel("top", true)
    void ask(q)
  }

  //: The chip's shortcut (#602): "elaborate" is the word the backend detects to
  //: switch into long-answer mode, so the chip needs no endpoint of its own.
  const elaborate = () => {
    if (pending) return
    void ask("elaborate on that")
  }

  const places = result?.places ?? []
  const events = result?.events ?? []
  const canAsk = query.trim().length > 0 && !pending

  return (
    //: Same left edge and same width as the deck below it, off one shared
    //: constant, because a column whose two halves are different widths reads
    //: as two things that happen to be stacked.
    <div
      className={cn(
        "pointer-events-none absolute z-40 flex flex-col gap-2",
        narrow
          ? //: Across the top of the phone, under whatever the hardware takes
            //: for its own status row. Not full height: the results hang from
            //: the bar and stop, because the bottom of the screen belongs to
            //: the sheet and a list that reaches it reads as part of it.
            "inset-x-2 top-[calc(env(safe-area-inset-top)+0.5rem)] max-h-[calc(60dvh)]"
          : "bottom-3 left-3 top-3",
      )}
      style={narrow ? undefined : { width: PANEL_WIDTH }}
    >
      <div
        className={cn(
          "pointer-events-auto flex items-center gap-2 rounded-2xl border border-white/10 bg-neutral-950/85 px-3 py-2 shadow-2xl shadow-black/60 backdrop-blur-xl",
          //: Every control in the bar becomes a thumb-sized target. Written
          //: once here rather than on each button: they are small for the
          //: same reason and stop being small at the same moment.
          narrow && "gap-1 [&_button]:min-h-11 [&_button]:min-w-11 [&_button]:justify-center",
        )}
      >
        <Search className="h-3.5 w-3.5 shrink-0 text-neutral-500" aria-hidden />
        <input
          ref={inputRef}
          value={query}
          onFocus={() => {
            setFocused(true)
            focusBar()
          }}
          onBlur={() => setFocused(false)}
          onChange={(e) => {
            setQuery(e.target.value)
            setDetail(null)
            setPanel("top", true)
          }}
          onKeyDown={(e) => {
            //: Enter asks. The search underneath has already answered by the
            //: time a key is pressed, so the only thing left for Enter to mean
            //: is the expensive question.
            if (e.key === "Enter") submitAsk()
          }}
          placeholder={narrow ? "ask or find…" : "ask anything, find anything…"}
          aria-label="Search the console or ask the brain"
          //: 16px on a phone, and not for legibility: below it mobile Safari
          //: zooms the page to the focused field on its own, and the console
          //: never zooms back out.
          className={cn(
            "min-w-0 flex-1 bg-transparent text-neutral-200 placeholder:text-neutral-600 focus:outline-none",
            narrow ? "text-base" : "text-[0.875rem]",
          )}
        />
        {busy && (
          <span className="shrink-0 font-mono text-[9px] uppercase tracking-widest text-neutral-600">
            …
          </span>
        )}
        <button
          type="button"
          onClick={submitAsk}
          disabled={!canAsk}
          className="shrink-0 rounded-lg border border-neutral-700/60 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-400 transition-colors hover:border-neutral-500 hover:text-neutral-100 disabled:opacity-40"
        >
          {pending ? "…" : "ask AI"}
        </button>
        {/*: Only while there is a search to leave. A permanent cross on an
            empty box is a control for undoing nothing. */}
        {searching && (
          <button
            type="button"
            onClick={clearSearch}
            aria-label="Clear search"
            title="Clear search (Esc)"
            className="shrink-0 text-neutral-500 transition-colors hover:text-neutral-200"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        )}
        <button
          type="button"
          onClick={() => setPanel("top", !open)}
          aria-expanded={open}
          aria-label={open ? "Hide results" : "Show results"}
          //: Disabled with nothing behind it: a control that opens an empty
          //: panel teaches the reader that the control does nothing.
          disabled={!searching}
          className="shrink-0 text-neutral-500 transition-transform hover:text-neutral-200 disabled:opacity-30"
        >
          <ChevronDown
            className={cn("h-4 w-4 transition-transform", open ? "" : "-rotate-90")}
            aria-hidden
          />
        </button>
      </div>

      {open && searching && (
        <div className="pointer-events-auto min-h-0 flex-1 overflow-y-auto rounded-2xl border border-white/10 bg-neutral-950/90 shadow-2xl shadow-black/60 backdrop-blur-xl">
          {/*: One box, two faces: the list, or the row the reader opened from
              it. Back rather than close, because the list is where they were
              and forty results are not worth retyping to get back to. */}
          {/*: The column is never blank while search holds it. Below the query
              floor there is nothing to list, so the panel says what the box is
              for rather than showing an empty rectangle where the deck was. */}
          {!detail && !typed && messages.length === 0 && (
            <p className="px-3 py-6 font-mono text-[10px] uppercase tracking-widest text-neutral-600">
              a place moves the map · a word finds what mentions it
            </p>
          )}

          {detail ? (
            <>
              <button
                type="button"
                onClick={() => setDetail(null)}
                className="flex w-full items-center gap-1.5 border-b border-neutral-800 px-3 py-2 text-left font-mono text-[9px] uppercase tracking-wide text-neutral-500 transition-colors hover:text-neutral-200"
              >
                <ChevronLeft className="h-3 w-3" aria-hidden />
                back to results
              </button>
              {/*: No location context. That is the map's account of why a
                  marker sits where it does, and a search result was not
                  clicked on the map — the card says "not recorded" rather
                  than being handed a provenance nobody established. */}
              <EventDetailCard
                event={detail}
                embedded
                onClose={() => setDetail(null)}
                onSelectCountry={openCountry}
              />
            </>
          ) : (
          <>
          {failed && (
            <p className="m-3 rounded-md border border-red-950 bg-red-950/20 px-3 py-3 text-xs text-red-300/80">
              Search is unavailable. The rest of the console is unaffected.
            </p>
          )}

          {typed && places.length > 0 && (
            <section>
              <p className="px-3 pb-1 pt-3 font-mono text-[9px] uppercase tracking-wide text-neutral-600">
                {/* Several places answering to one name is a question, not an
                    answer — five Springfields are five different towns. */}
                {places.length > 1 ? `${places.length} places match — pick one` : "place"}
              </p>
              <ul className="divide-y divide-neutral-800/60">
                {places.map((p) => (
                  <li key={`${p.name}:${p.lat}:${p.lon}`}>
                    <button
                      type="button"
                      onClick={() => {
                        //: The list stays. Eight places answer to "ed" and
                        //: only the reader knows which they meant, so a click
                        //: is usually a look rather than a decision, and
                        //: closing the list on it makes checking the second
                        //: candidate a retype.
                        flyTo(p.lat, p.lon, ZOOM_BY_KIND[p.kind])
                      }}
                      className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left transition-colors hover:bg-neutral-900/40"
                    >
                      <span className="text-[11.5px] text-neutral-200">{p.name}</span>
                      <span className="min-w-0 flex-1 truncate font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                        {p.context}
                      </span>
                      <span className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-neutral-700">
                        {p.kind}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {typed && events.length > 0 && (
            <section>
              <p className="px-3 pb-1 pt-3 font-mono text-[9px] uppercase tracking-wide text-neutral-600">
                {events.length} {events.length === 1 ? "result" : "results"}
              </p>
              {/* Same row shape as the selection list — index, clock, headline
                  with room to wrap. A second list style is a second thing to
                  learn for no gain. */}
              <ul className="divide-y divide-neutral-800/60">
                {events.map((ev, i) => (
                  <li key={ev.id}>
                    <button
                      type="button"
                      onClick={() => {
                        //: Opens in this box, not the deck's pop-up (#938).
                        setDetail(asVisible(ev))
                        //: Move the map only when the row knows where it is.
                        //: Nothing invented (#719, #756).
                        if (ev.lat != null && ev.lon != null) flyTo(ev.lat, ev.lon, 8)
                      }}
                      className="flex w-full items-start gap-2 px-3 py-1.5 text-left transition-colors hover:bg-neutral-900/40"
                    >
                      <span className="w-5 shrink-0 pt-0.5 text-right font-mono text-[10px] tabular-nums text-neutral-600">
                        {i + 1}
                      </span>
                      <span
                        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ backgroundColor: colorForEvent(ev) }}
                      />
                      <span className="w-10 shrink-0 pt-0.5 font-mono text-[10px] tabular-nums text-neutral-500">
                        {clockTime(ev.occurred_at)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span
                          className="block overflow-hidden text-[11.5px] leading-4 text-neutral-300"
                          style={{
                            display: "-webkit-box",
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: "vertical",
                          }}
                        >
                          {eventHeadline(ev)}
                        </span>
                        <span className="mt-0.5 block truncate font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                          {[ev.source.replace(/^rss-/, ""), ev.country].filter(Boolean).join(" · ")}
                          {ev.lat == null && " · no location"}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {typed && !busy && !failed && places.length === 0 && events.length === 0 && (
            <p className="px-3 py-6 font-mono text-[10px] uppercase tracking-widest text-neutral-600">
              nothing matches “{query.trim()}”
            </p>
          )}

          {messages.length > 0 && (
            <section className="border-t border-neutral-800">
              <div className="flex items-baseline justify-between px-3 pt-2">
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
              <div className="divide-y divide-neutral-800/60 px-3 pb-2">
                {messages.map((m, i) => (
                  <ChatEntry
                    key={i}
                    m={m}
                    onOpenStory={openStory}
                    //: Only the latest, finalized answer gets the chip —
                    //: retrieval anchors on the most recent exchange, so
                    //: elaborating an older one would drift topic (#602).
                    onElaborate={
                      i === messages.length - 1 && !m.draft && !pending ? elaborate : undefined
                    }
                  />
                ))}
              </div>
            </section>
          )}
          </>
          )}
        </div>
      )}
    </div>
  )
}
