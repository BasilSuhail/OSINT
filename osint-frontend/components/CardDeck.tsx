"use client"

import { Maximize2, Minimize2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"

export interface DeckCard {
  key: string
  title: string
  /** fill: content manages its own layout (absolute-inset surfaces like the
   *  console or the globe). Otherwise the card body is a padded scroller. */
  fill?: boolean
  /** lazy: mount the content on first visit only, then keep it warm — for
   *  expensive surfaces (the globe's WebGL context). */
  lazy?: boolean
  /** Plain node, or a function of whether this card is the active page —
   *  lets heavy content (the globe) pause itself while off-screen. */
  content: React.ReactNode | ((isActive: boolean) => React.ReactNode)
}

const SWIPE_FINGERS = 3
const SWIPE_THRESHOLD_PX = 60

/** The right pane as a deck of swipeable cards (#328).
 *
 *  One card per page, native horizontal scroll-snap — a two-finger trackpad
 *  swipe just works. The globe card deliberately keeps two-finger gestures
 *  for itself (orbit/zoom, its canvas consumes them), so on touch screens a
 *  THREE-finger swipe flips pages from anywhere, globe included; on
 *  trackpads (where the browser cannot see finger count) the paging dots
 *  and title do the job while the globe is up.
 *
 *  The expand control grows the deck in place to cover the page below the
 *  status bar — a CSS toggle on the same DOM node, so nothing remounts and
 *  the globe's WebGL context stays warm. Esc collapses; while the console
 *  card has an entity locked, Esc belongs to the entity close handler
 *  first. */
export function CardDeck({ cards }: { cards: DeckCard[] }) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const activeRef = useRef(0)
  // Lazy cards mount on first visit and stay mounted (kept warm).
  const [visited, setVisited] = useState<ReadonlySet<number>>(() => new Set([0]))

  const setActiveIndex = useCallback((i: number) => {
    activeRef.current = i
    setActive(i)
    setVisited((v) => (v.has(i) ? v : new Set(v).add(i)))
  }, [])

  const onScroll = useCallback(() => {
    const el = trackRef.current
    if (!el || el.clientWidth === 0) return
    const i = Math.round(el.scrollLeft / el.clientWidth)
    setActiveIndex(Math.max(0, Math.min(cards.length - 1, i)))
  }, [cards.length, setActiveIndex])

  const goTo = useCallback(
    (i: number, smooth = true) => {
      const el = trackRef.current
      if (!el) return
      const clamped = Math.max(0, Math.min(cards.length - 1, i))
      el.scrollTo({ left: clamped * el.clientWidth, behavior: smooth ? "smooth" : "instant" })
    },
    [cards.length],
  )

  // Re-align the active card whenever the deck's width changes (pane resize,
  // expand/collapse) — scroll-snap keeps offsets, not indices.
  useEffect(() => {
    const el = trackRef.current
    if (!el) return
    const observer = new ResizeObserver(() => goTo(activeRef.current, false))
    observer.observe(el)
    return () => observer.disconnect()
  }, [goTo])

  // Three-finger swipe pages the deck even over surfaces that own two-finger
  // gestures (the globe). Capture phase so the canvas cannot swallow it.
  useEffect(() => {
    const el = trackRef.current
    if (!el) return
    let startX: number | null = null
    const onTouchStart = (e: TouchEvent) => {
      startX = e.touches.length === SWIPE_FINGERS ? e.touches[0].clientX : null
    }
    const onTouchMove = (e: TouchEvent) => {
      if (startX == null || e.touches.length !== SWIPE_FINGERS) return
      const dx = e.touches[0].clientX - startX
      if (Math.abs(dx) < SWIPE_THRESHOLD_PX) return
      e.preventDefault()
      startX = null
      goTo(activeRef.current + (dx < 0 ? 1 : -1))
    }
    const onTouchEnd = () => {
      startX = null
    }
    el.addEventListener("touchstart", onTouchStart, { capture: true, passive: true })
    el.addEventListener("touchmove", onTouchMove, { capture: true, passive: false })
    el.addEventListener("touchend", onTouchEnd, { capture: true, passive: true })
    return () => {
      el.removeEventListener("touchstart", onTouchStart, { capture: true })
      el.removeEventListener("touchmove", onTouchMove, { capture: true })
      el.removeEventListener("touchend", onTouchEnd, { capture: true })
    }
  }, [goTo])

  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      // An open entity owns Esc — collapse only once it is closed.
      if (useRightPaneModeStore.getState().entity) return
      setExpanded(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [expanded])

  return (
    <div
      className={
        expanded
          ? "fixed inset-x-0 bottom-0 top-8 z-[60] bg-neutral-950"
          : "relative h-full w-full bg-neutral-950"
      }
    >
      <div className="flex h-full flex-col">
        <div className="flex h-8 shrink-0 items-center justify-between px-3">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? "back to console (esc)" : "cover the full page"}
            className="font-mono text-[10px] uppercase tracking-widest text-neutral-400 transition-colors hover:text-cyan-300"
          >
            {cards[active]?.title}
          </button>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? "Collapse card" : "Expand card to full page"}
            className="flex items-center gap-1.5 rounded-md border border-neutral-800 px-2 py-0.5 font-mono text-[9px] uppercase tracking-widest text-neutral-400 transition-colors hover:border-cyan-500/60 hover:text-cyan-300"
          >
            {expanded ? (
              <>
                <Minimize2 className="h-3 w-3" /> esc
              </>
            ) : (
              <Maximize2 className="h-3 w-3" />
            )}
          </button>
        </div>

        <div
          ref={trackRef}
          onScroll={onScroll}
          className="flex min-h-0 flex-1 snap-x snap-mandatory overflow-x-auto overflow-y-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {cards.map((card, i) => (
            <section
              key={card.key}
              aria-label={card.title}
              className="h-full w-full shrink-0 snap-start p-1.5 pt-0"
            >
              <div className="h-full w-full overflow-hidden rounded-2xl border border-neutral-800 bg-neutral-900/40">
                {card.lazy && !visited.has(i) ? null : card.fill ? (
                  <div className="relative h-full w-full">
                    {typeof card.content === "function" ? card.content(i === active) : card.content}
                  </div>
                ) : (
                  <div className="h-full w-full overflow-y-auto p-3">
                    <div className="mx-auto w-full max-w-5xl">
                      {typeof card.content === "function" ? card.content(i === active) : card.content}
                    </div>
                  </div>
                )}
              </div>
            </section>
          ))}
        </div>

        <div className="flex h-7 shrink-0 items-center justify-center gap-2">
          {cards.map((card, i) => (
            <button
              key={card.key}
              type="button"
              onClick={() => goTo(i)}
              aria-label={`Go to ${card.title}`}
              title={card.title}
              className={
                i === active
                  ? "h-1.5 w-4 rounded-full bg-neutral-200"
                  : "h-1.5 w-1.5 rounded-full bg-neutral-600 transition-colors hover:bg-neutral-400"
              }
            />
          ))}
        </div>
      </div>
    </div>
  )
}
