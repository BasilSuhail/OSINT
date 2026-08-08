"use client"

import { ChevronLeft, ChevronRight } from "lucide-react"
import dynamic from "next/dynamic"
import { useCallback, useEffect, useState } from "react"
import { useConfigured } from "@/app/providers"
import type { VisibleEvent } from "@/lib/queries"
import type { MarkerLocationContext } from "@/lib/locationProvenance"
import { useMediaQuery } from "@/lib/useMediaQuery"
import { useLeftPaneStore } from "@/stores/leftPaneStore"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { useStoryDetailStore } from "@/stores/storyDetailStore"
import { useWorldDetailStore } from "@/stores/worldDetailStore"
import useSWR from "swr"
import { fetchScoreboard } from "@/lib/analytics"
import { scoreboardIsReady } from "@/lib/deckReadiness"
import { CardDeck, type DeckCard } from "./CardDeck"
import { FloatingPanel } from "./FloatingPanel"
import { SearchPanel } from "./SearchPanel"
import { BriefingPanel } from "./panels/BriefingPanel"
import { WorldHeadline, WorldStatusPanel } from "./WorldStatusPanel"
import { StoryDetailCard } from "./panels/StoryDetailCard"
import { WorldDetailCard } from "./panels/WorldDetailCard"
import { CoveragePanel } from "./panels/CoveragePanel"
import { TrustPanel } from "./panels/TrustPanel"
import { SelectionPanel } from "./panels/SelectionPanel"
import { ScoreboardPanel } from "./panels/ScoreboardPanel"
import { SituationPanel } from "./panels/SituationPanel"
import { StoriesPanel } from "./panels/StoriesPanel"
import { SystemStatusBar } from "./SystemStatusBar"

const MapPane = dynamic(() => import("./MapPane").then((m) => m.MapPane), {
  ssr: false,
  loading: () => <PaneSkeleton label="map" />,
})
//: RightPane is superseded by #699 — its world half is WorldStatusPanel and its
//: entity half is the selection card, so the deck no longer mounts it. The file
//: stays on disk; removing panels is a separate decision from what the deck
//: shows.

/** Deck and detail share one width so the pop-out lines up with the deck
 *  without measuring anything at runtime (#503). */
const PANEL_WIDTH = "clamp(320px, 28vw, 460px)"

function PaneSkeleton({ label }: { label: string }) {
  return (
    <div className="grid h-full w-full place-items-center bg-neutral-950">
      <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-700">
        initialising {label}…
      </span>
    </div>
  )
}

export function SplitLayout() {
  const configured = useConfigured()
  const isNarrow = useMediaQuery("(max-width: 900px)")

  const [leftRailOpen, setLeftRailOpen] = useState(false)
  const [activePane, setActivePane] = useState<"left" | "right">("left")
  const [, setLeftCount] = useState(0)
  //: Transient "let me see the map" gesture, not a stored preference (#503).
  const [deckCollapsed, setDeckCollapsed] = useState(false)

  // Selections drive the right pane's entity-lock mode (#252). The clicked
  // event id also expands its hazard footprint on the map.
  //: Story pop-out (#448): a second card left of the deck, same width.
  const storyDetailOpen = useStoryDetailStore((s) => s.storyId !== null)
  const worldDetailOpen = useWorldDetailStore((s) => s.open)
  //: One slot, whichever tile asked for it (#705). A story wins if both are
  //: somehow set — opening one never closes the other, so it is the later click.
  const sidePanel = storyDetailOpen ? "story" : worldDetailOpen ? "world" : null
  const entity = useRightPaneModeStore((s) => s.entity)
  const openEvent = useRightPaneModeStore((s) => s.openEvent)
  const [searchOpen, setSearchOpen] = useState(false)
  const selectedEventId = entity?.kind === "event" ? entity.event.id : null

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      //: Esc closes the story pop-out from anywhere, even while typing.
      if (e.key === "Escape") {
        useStoryDetailStore.getState().closeStory()
        return
      }
      const target = e.target as HTMLElement
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return
      if (e.key === "[") {
        setLeftRailOpen((o) => !o)
      } else if (e.key === "]") {
        //: `]` used to toggle the right rail, which left with the globe (#494).
        setDeckCollapsed((c) => !c)
      } else if (e.key === " ") {
        e.preventDefault()
        //: The map is the only scrubbable surface now that the globe is gone.
        useLeftPaneStore.getState().togglePlaying()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  // Selecting anything locks the right pane to that entity; on the narrow
  // single-column layout, reveal the right pane so the detail is visible.
  const onSelectEvent = useCallback(
    (ev: VisibleEvent, location?: MarkerLocationContext) => {
      openEvent(ev, location)
      if (isNarrow) setActivePane("right")
    },
    [openEvent, isNarrow],
  )
  const onOpenMapSelection = useCallback(() => {
    if (isNarrow) setActivePane("right")
  }, [isNarrow])

  // The right pane as a card deck (#328): console keeps its world-status /
  // entity surface and the analytical pages fill the rest. The globe card was
  // removed in #494 — its WebGL context was the tab's largest memory holder.
  const { data: scoreboardRows } = useSWR("deck-scoreboard-ready", fetchScoreboard)
  const scoreboardReady = scoreboardIsReady(scoreboardRows)
  const selection = useRightPaneModeStore((s) => s.entity)

  const deckCards: DeckCard[] = [
    //: fill — the panel is its own scroll surface (live list + transcript) with
    //: a fixed ask-box footer; the deck's non-fill outer scroll would defeat it.
    { key: "situation", title: "situation", fill: true, content: <SituationPanel /> },
    //: Two halves (#699). Collapsed: the totals graph as a door, and the
    //: stories summary — counts, window, owner floor, confidence spread — with
    //: the two hundred rows folded away, because a list is not a summary.
    //: Expanded: ranked countries, per-country coverage, and the briefing.
    {
      key: "world",
      title: "world",
      collapsedContent: (
        <div className="flex h-full w-full flex-col">
          {/* Search sits above everything on this card, because it is the way
              into the system rather than a filter over one panel (#779).
              Focused, it takes the whole card: results need the room, and a
              list squeezed under a dashboard is not a list. */}
          <div className={searchOpen ? "flex min-h-0 flex-1 flex-col" : "shrink-0"}>
            <SearchPanel
              open={searchOpen}
              onOpenChange={setSearchOpen}
              onSelectEvent={(ev) => openEvent(ev)}
            />
          </div>
          {!searchOpen && (
            <>
              {/* Sizes to its content (#711). A fixed half left the title, three
                  numbers and a sparkline floating in the middle of a tall box with
                  a gap above and below. */}
              <div className="shrink-0 border-b border-neutral-800">
                <WorldHeadline />
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                <StoriesPanel tuckRows />
              </div>
            </>
          )}
        </div>
      ),
      fill: true,
      content: (
        <div className="h-full w-full overflow-y-auto">
          <div className="h-[60vh]">
            <WorldStatusPanel />
          </div>
          <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-3">
            {/* First, deliberately: whether the console can be trusted comes
                before what it is saying (#828). */}
            <TrustPanel />
            <CoveragePanel />
            <BriefingPanel />
            <StoriesPanel />
          </div>
        </div>
      ),
    },
  ]

  //: The card that is not there most of the time (#699). A map click opens it,
  //: Escape closes it, and it sits after the standing cards so those never get
  //: shoved sideways — a deck whose pages move is not a place you can learn.
  if (selection) {
    deckCards.push({
      key: "selection",
      title: "selection",
      fill: true,
      content: <SelectionPanel />,
    })
  }

  //: The scoreboard shows itself once it has something graded (#694). Every
  //: Brier is null today because nothing has matured, and an empty table
  //: promising a track record is the one thing this card must never be. It
  //: returns on its own — no flag to flip, nothing to remember.
  if (scoreboardReady) {
    deckCards.push({ key: "scoreboard", title: "scoreboard", content: <ScoreboardPanel /> })
  }

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-neutral-950 text-neutral-100">
      <SystemStatusBar useStore={useLeftPaneStore} />
      <div className="relative h-[calc(100dvh-2rem)] w-full overflow-hidden">
        {!configured && (
          <div className="absolute inset-x-0 top-0 z-50 bg-red-950/90 px-4 py-2 text-center font-mono text-xs text-red-200 backdrop-blur">
            Local API unreachable - start it at NEXT_PUBLIC_API_URL (default http://localhost:8000)
          </div>
        )}

        {isNarrow ? (
          <div className="relative h-full w-full">
            <div className="pointer-events-auto absolute left-1/2 top-12 z-40 -translate-x-1/2 flex gap-1 rounded-full border border-neutral-800 bg-neutral-950/80 p-1 backdrop-blur-sm">
              {(["left", "right"] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setActivePane(p)}
                  className={
                    "rounded-full px-3 py-1 font-mono text-[10px] uppercase tracking-widest transition-colors " +
                    (activePane === p
                      ? "bg-neutral-800 text-neutral-100"
                      : "text-neutral-500 hover:text-neutral-300")
                  }
                >
                  {p === "left" ? "map" : "panel"}
                </button>
              ))}
            </div>

            <div className="absolute inset-0 z-0">
              <MapPane
                useStore={useLeftPaneStore}
                railOpen={leftRailOpen}
                onRailOpenChange={setLeftRailOpen}
                onCount={setLeftCount}
                onOpenSelection={onOpenMapSelection}
                onSelectEvent={onSelectEvent}
                selectedEventId={selectedEventId}
              />
            </div>
            <div
              className="absolute inset-x-2 bottom-2 top-20 z-30"
              style={{ display: activePane === "right" ? "block" : "none" }}
            >
              <FloatingPanel className="h-full w-full">
                {sidePanel === "story" ? (
                  <StoryDetailCard />
                ) : sidePanel === "world" ? (
                  <WorldDetailCard />
                ) : (
                  <CardDeck cards={deckCards} />
                )}
              </FloatingPanel>
            </div>
          </div>
        ) : (
          //: Layered stage (#503): the map is the base layer and fills the
          //: viewport; everything else floats above it. No panel group, no
          //: resize handle — those are what made the console read as boxed.
          <div
            className="relative h-full w-full"
            //: Total width occupied by floating panels on the left edge,
            //: published to descendants so map-level overlays (the scrubber)
            //: stop short of them instead of sliding underneath. Counts the
            //: detail card too when it is open, and collapses to 0 with the deck.
            style={
              {
                "--panel-width": deckCollapsed
                  ? "0px"
                  : sidePanel
                    ? `calc(${PANEL_WIDTH} * 2 + 0.5rem)`
                    : PANEL_WIDTH,
              } as React.CSSProperties
            }
          >
            <div className="absolute inset-0 z-0">
              <MapPane
                useStore={useLeftPaneStore}
                railOpen={leftRailOpen}
                onRailOpenChange={setLeftRailOpen}
                onCount={setLeftCount}
                onOpenSelection={onOpenMapSelection}
                onSelectEvent={onSelectEvent}
                selectedEventId={selectedEventId}
              />
            </div>

            {/* With a fixed deck width the pop-out's position is arithmetic
             *  rather than plumbing the panel's measured pixels. */}
            {sidePanel && !deckCollapsed ? (
              <FloatingPanel
                className="absolute bottom-3 top-3 z-30"
                style={{ width: PANEL_WIDTH, left: `calc(${PANEL_WIDTH} + 1.25rem)` }}
              >
                {sidePanel === "story" ? <StoryDetailCard /> : <WorldDetailCard />}
              </FloatingPanel>
            ) : null}

            {/* Collapse handle rides the outer edge of whatever is showing,
             *  tracked by --panel-width. It cannot live inside the deck: that
             *  header row already has the card title on the left and the expand
             *  control on the right. */}
            <button
              type="button"
              onClick={() => setDeckCollapsed((c) => !c)}
              title={deckCollapsed ? "Show panel (])" : "Hide panel (])"}
              style={{ left: `calc(var(--panel-width) + 1rem)` }}
              className="absolute top-1/2 z-30 -translate-y-1/2 rounded-l-md rounded-r-xl border border-white/10 bg-neutral-950/85 px-1.5 py-6 text-neutral-400 shadow-2xl shadow-black/60 backdrop-blur-xl transition-colors hover:text-neutral-100"
            >
              {deckCollapsed ? (
                <ChevronRight size={16} aria-hidden />
              ) : (
                <ChevronLeft size={16} aria-hidden />
              )}
              <span className="sr-only">{deckCollapsed ? "Show panel" : "Hide panel"}</span>
            </button>

            {deckCollapsed ? null : (
              <FloatingPanel
                className="absolute bottom-3 left-3 top-3 z-30"
                style={{ width: PANEL_WIDTH }}
              >
                <CardDeck cards={deckCards} />
              </FloatingPanel>
            )}
          </div>
        )}
      </div>
    </main>
  )
}
