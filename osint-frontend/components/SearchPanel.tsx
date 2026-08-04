"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Search, X } from "lucide-react"
import { fetchSearch, type SearchPlace, type SearchResponse } from "@/lib/apiClient"
import type { VisibleEvent } from "@/lib/queries"
import type { EventRow } from "@/lib/types"
import { colorForEvent } from "@/lib/types"

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

function eventTitle(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const title =
    (typeof p.title === "string" && p.title) ||
    (typeof p.headline === "string" && p.headline) ||
    null
  if (title) return title
  //: GDELT carries no headline — action plus place is the most it can
  //: honestly say (#733).
  const label = typeof p.action_label === "string" ? p.action_label : null
  if (label) {
    const where = typeof p.geo_name === "string" ? p.geo_name.split(",")[0]?.trim() : null
    return where ? `${label} · ${where}` : label
  }
  return ev.source
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

/**
 * The search surface over the world card (#779).
 *
 * Focus clears the card to full height, because results need the room and a
 * list squeezed under a dashboard is not a list. Escape restores it.
 *
 * A query is answered two ways at once: the gazetteer says whether it names
 * a place, and full-text says which stories mention it. Both are shown and
 * the reader picks — "Manchester" is a city and a football club, and only
 * they know which they meant.
 */
export function SearchPanel({
  open,
  onOpenChange,
  onSelectEvent,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelectEvent: (ev: VisibleEvent) => void
}) {
  const [query, setQuery] = useState("")
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const close = useCallback(() => {
    abortRef.current?.abort()
    setQuery("")
    setResult(null)
    setFailed(false)
    onOpenChange(false)
  }, [onOpenChange])

  //: Esc closes search before anything else sees it. Without stopping
  //: propagation the same press also sends the deck home, and the reader
  //: loses both their query and their place in one keystroke.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      e.stopPropagation()
      close()
    }
    window.addEventListener("keydown", onKey, { capture: true })
    return () => window.removeEventListener("keydown", onKey, { capture: true })
  }, [open, close])

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

  const places = result?.places ?? []
  const events = result?.events ?? []
  const typed = query.trim().length >= MIN_QUERY

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-neutral-800 px-3 py-2">
        <Search className="h-3.5 w-3.5 shrink-0 text-neutral-500" aria-hidden />
        <input
          ref={inputRef}
          value={query}
          onFocus={() => onOpenChange(true)}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search places, stories, sensors…"
          aria-label="Search everything"
          className="min-w-0 flex-1 bg-transparent font-mono text-xs text-neutral-200 placeholder:text-neutral-600 focus:outline-none"
        />
        {busy && (
          <span className="shrink-0 font-mono text-[9px] uppercase tracking-widest text-neutral-600">
            …
          </span>
        )}
        {open && (
          <button
            type="button"
            onClick={close}
            aria-label="Close search"
            className="shrink-0 text-neutral-500 hover:text-neutral-200"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {open && (
        <div className="min-h-0 flex-1 overflow-y-auto">
          {!typed && (
            <p className="px-3 py-6 font-mono text-[10px] uppercase tracking-widest text-neutral-600">
              a place moves the map · a word finds what mentions it
            </p>
          )}

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
                      onClick={() => flyTo(p.lat, p.lon, ZOOM_BY_KIND[p.kind])}
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
                        onSelectEvent(asVisible(ev))
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
                          {eventTitle(ev)}
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
        </div>
      )}
    </div>
  )
}
