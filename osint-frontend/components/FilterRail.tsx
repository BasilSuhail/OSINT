"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Droplets,
  Flame,
  Landmark,
  type LucideIcon,
  Mountain,
  Newspaper,
  RotateCcw,
  Search,
  SlidersHorizontal,
  ShieldAlert,
  Snowflake,
  Sun,
  TrendingUp,
  Triangle,
  Wind,
  X,
} from "lucide-react"
import { formatDistanceToNowStrict } from "date-fns"
import { useEvents } from "@/app/providers"
import { mergeEventRows } from "@/lib/eventMerge"
import { useEventsInWindow } from "@/lib/queries"
import {
  HAZARD_SOURCE_KEYS,
  HAZARD_TYPE_FILTERS,
  SOURCE_FILTERS,
  sourceKeyForEvent,
  type EventRow,
  type HazardTypeKey,
  type SourceKey,
} from "@/lib/types"
import { hazardKind } from "@/lib/hazardSymbols"
import { cameoLabel } from "@/lib/cameo"
import { countryCodesForEvent } from "@/lib/countryMatching"
import { mapSummary } from "@/lib/mapSummary"
import {
  FULL_SEVERITY,
  activeExclusions,
  filtersHideEverything,
  severityIsNarrowed,
} from "@/lib/filterExclusions"
import type { FilterStore } from "@/stores/createFilterStore"
import { cn } from "@/lib/utils"
import { IMAGERY_LAYERS, imageryDate } from "@/lib/imageryLayers"
import { useImageryStore } from "@/stores/imageryStore"
import { usePresenceStore } from "@/stores/presenceStore"
import { windowIsNow } from "@/lib/presence"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Input } from "@/components/ui/input"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

const regionNames =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null

function countryDisplayName(iso: string): string {
  try {
    return regionNames?.of(iso) ?? iso
  } catch {
    return iso
  }
}

function severityBarColor(s: number): string {
  if (s >= 0.8) return "#ef4444"
  if (s >= 0.6) return "#f97316"
  if (s >= 0.4) return "#eab308"
  return "#22c55e"
}

function eventListTitle(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const src = (ev.source || "").toLowerCase()
  if (src === "gdelt") {
    const cameo = cameoLabel(p?.event_root_code as string | number | undefined)
    if (cameo) return cameo
  }
  if (src === "acled") {
    const type = typeof p?.event_type === "string" ? p.event_type : null
    const loc = typeof p?.location === "string" ? p.location : null
    if (type && loc) return `${type} · ${loc}`
    if (type) return type
  }
  if (src === "usgs-quake") {
    const mag = typeof p?.magnitude === "number" ? p.magnitude : null
    if (mag !== null) return `M${mag.toFixed(1)} quake`
  }
  if (src === "gdacs") {
    const t = typeof p?.event_type === "string" ? p.event_type : null
    if (t) return t.toUpperCase()
  }
  if (src === "emdat") {
    const t = typeof p?.disaster_type === "string" ? p.disaster_type : null
    const loc = typeof p?.country_name === "string" ? p.country_name : null
    if (t && loc) return `${t} · ${loc}`
    if (t) return t
  }
  if (src === "nasa-firms") return "Active fire"
  if (src === "eonet") {
    const cats = Array.isArray(p?.categories) ? (p.categories as string[]) : null
    if (cats && cats[0]) return cats[0]
  }
  if (src === "yfinance" || src === "yf") {
    const tkr = typeof p?.ticker === "string" ? p.ticker : null
    if (tkr) return `${tkr} drawdown`
  }
  if (src === "fred") {
    const series = typeof p?.series_id === "string" ? p.series_id : null
    if (series) return `${series} macro`
  }
  const title = typeof p?.title === "string" ? p.title : null
  return title ?? ev.source
}

function countryFlagEmoji(iso: string): string {
  if (!iso || iso.length !== 2) return ""
  const codePoints = iso
    .toUpperCase()
    .split("")
    .map((c) => 127397 + c.charCodeAt(0))
  return String.fromCodePoint(...codePoints)
}

/** Per-source type icon so the rail reads at a glance (quake / fire / storm…)
 *  instead of a bare colour dot. */
const SOURCE_ICONS: Record<SourceKey, LucideIcon> = {
  NEWS: Newspaper,
  GDELT: Landmark,
  ACLED: ShieldAlert,
  EMDAT: AlertTriangle,
  USGS: Activity,
  GDACS: AlertTriangle,
  EONET: Mountain,
  yfinance: TrendingUp,
  FRED: Landmark,
  CYBER: ShieldAlert,
  POLYMARKET: TrendingUp,
}

/** Disaster-type icons — match the map pins (quake waveform, fire flame, …). */
const HAZARD_TYPE_ICONS: Record<HazardTypeKey, LucideIcon> = {
  EQ: Activity,
  TC: Wind,
  FL: Droplets,
  WF: Flame,
  VO: Triangle,
  DR: Sun,
  ICE: Snowflake,
}

/** A group's caption, outside its container — the list's only headings. */
function GroupCaption({
  label,
  note,
  onAll,
  onNone,
}: {
  label: string
  note?: string
  onAll?: () => void
  onNone?: () => void
}) {
  return (
    <div className="mb-1.5 flex items-center justify-between px-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
        {label}
      </span>
      {onAll && onNone ? (
        <span className="flex items-center gap-1">
          <button
            type="button"
            onClick={onAll}
            className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-neutral-500 transition-colors hover:bg-white/10 hover:text-neutral-100"
          >
            All
          </button>
          <button
            type="button"
            onClick={onNone}
            className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-neutral-500 transition-colors hover:bg-white/10 hover:text-neutral-100"
          >
            None
          </button>
        </span>
      ) : note ? (
        <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-600">
          {note}
        </span>
      ) : null}
    </div>
  )
}

/** The inset container every group's rows sit in: one border, hairlines
 *  between rows, no border per row. The list reads as a list. */
function ListGroup({ children }: { children: React.ReactNode }) {
  return (
    <div className="divide-y divide-white/5 overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
      {children}
    </div>
  )
}

/** One row: what it is on the left, how many there are, and its switch. */
function ToggleRow({
  icon: Icon,
  hex,
  label,
  hint,
  count,
  on,
  disabled,
  onToggle,
}: {
  icon?: LucideIcon
  hex?: string
  label: string
  hint?: string
  count?: number
  on: boolean
  disabled?: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      //: No aria-label: it would replace the accessible name with the bare
      //: label and silence the count beside it and the hint beneath it — the
      //: line that explains why Military air is disabled lives in the hint.
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors",
        disabled ? "cursor-not-allowed opacity-40" : "hover:bg-white/[0.04]",
      )}
    >
      {Icon && hex && (
        <span
          className="grid h-6 w-6 shrink-0 place-items-center rounded-[7px] transition-opacity"
          style={{ backgroundColor: hex, opacity: on ? 1 : 0.3 }}
        >
          <Icon className="h-3.5 w-3.5 text-neutral-950" strokeWidth={2.5} aria-hidden />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block truncate text-[13px]",
            on ? "text-neutral-100" : "text-neutral-400",
          )}
        >
          {label}
        </span>
        {hint && (
          <span className="mt-0.5 block truncate font-mono text-[10px] text-neutral-600">
            {hint}
          </span>
        )}
      </span>
      {typeof count === "number" && (
        <span className="shrink-0 font-mono text-[11px] tabular-nums text-neutral-500">
          {count.toLocaleString()}
        </span>
      )}
      {/*: A switch, not a checkbox: these say what the map is showing right
          now, which is a state, not a form field waiting to be submitted. */}
      <span
        aria-hidden
        className={cn(
          "relative h-[18px] w-[30px] shrink-0 rounded-full transition-colors",
          on ? "bg-emerald-500" : "bg-white/15",
        )}
      >
        <span
          className={cn(
            "absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white transition-transform",
            on ? "translate-x-[14px]" : "translate-x-[2px]",
          )}
        />
      </span>
    </button>
  )
}

interface FilterRailProps {
  side: "left" | "right"
  useStore: FilterStore
  open: boolean
  onOpenChange: (open: boolean) => void
  supplementalEvents?: EventRow[]
}

const NO_SUPPLEMENTAL_EVENTS: EventRow[] = []

export function FilterRail({
  side,
  useStore,
  open,
  onOpenChange,
  supplementalEvents = NO_SUPPLEMENTAL_EVENTS,
}: FilterRailProps) {
  const baseEvents = useEvents()
  const allEvents = useMemo(
    () => mergeEventRows(baseEvents, supplementalEvents),
    [baseEvents, supplementalEvents],
  )
  const sources = useStore((s) => s.sources)
  const severity = useStore((s) => s.severity)
  const countries = useStore((s) => s.countries)
  const keyword = useStore((s) => s.keyword)
  const toggleSource = useStore((s) => s.toggleSource)
  const setAllSources = useStore((s) => s.setAllSources)
  const hazardTypes = useStore((s) => s.hazardTypes)
  const toggleHazardType = useStore((s) => s.toggleHazardType)
  const setAllHazardTypes = useStore((s) => s.setAllHazardTypes)
  const setSeverity = useStore((s) => s.setSeverity)
  const toggleCountry = useStore((s) => s.toggleCountry)
  const setKeyword = useStore((s) => s.setKeyword)
  const reset = useStore((s) => s.reset)

  const [countryOpen, setCountryOpen] = useState(false)
  //: The rail can be put away entirely. Hovering the pane edge opens it, which
  //: is convenient until the thing you want to look at is *under* it — the
  //: strip covers a column of the map and re-opens the moment the cursor
  //: passes. Hidden, only a small handle remains, and no hover reaches it.
  const [hidden, setHidden] = useState(false)

  //: The backdrop reads the same clock the markers do (#875).
  const activeImagery = useImageryStore((s) => s.active)
  const imageryMissing = useImageryStore((s) => s.missing)
  const toggleImagery = useImageryStore((s) => s.toggle)
  const windowEndOffsetMs = useStore((s) => s.windowEndOffsetMs)
  const imageryDay = imageryDate(Date.now() - windowEndOffsetMs)

  //: Live aircraft (#873). Hidden rather than disabled when the scrubber
  //: leaves "now": nothing about presence is stored, so there is no past to
  //: show, and a live layer over an old map would read as history.
  const presenceOn = usePresenceStore((st) => st.aircraft)
  const togglePresence = usePresenceStore((st) => st.toggleAircraft)
  const presenceAtNow = windowIsNow(windowEndOffsetMs)

  /** Windowed count for the rail header — the same pipeline the map markers
   *  use, so the header and the dots always agree. The event *list* left with
   *  the EVENTS tab (#510); reading events is the situation list's job. */
  const { events: visibleEvents, total: visibleTotal } = useEventsInWindow(
    useStore,
    supplementalEvents,
  )

  //: What is on the map, counted from the events that survived the filters —
  //: the same list the markers are drawn from, so the header and the map can
  //: never disagree about what is being looked at.
  const summaryChips = useMemo(() => mapSummary(visibleEvents), [visibleEvents])

  /** Source toggles, minus the hazard sources (USGS / GDACS / EONET) — those
   *  are filtered by disaster type instead, below. */
  const paneFilters = useMemo(
    () => SOURCE_FILTERS.filter((f) => !HAZARD_SOURCE_KEYS.includes(f.key)),
    [],
  )

  /** Events that could appear on the map: anything with a known source key.
   *  sourceKeyForEvent returns null for feeds with no renderer (NASA FIRMS,
   *  aviation), so they never reach the counts. */
  const paneEvents = useMemo(() => {
    return allEvents.filter((ev) => sourceKeyForEvent(ev) !== null)
  }, [allEvents])

  /** Live count of pane-scoped events per source — drives the per-row badges. */
  const sourceCounts = useMemo(() => {
    const m = new Map<SourceKey, number>()
    for (const ev of paneEvents) {
      const sk = sourceKeyForEvent(ev)
      if (sk) m.set(sk, (m.get(sk) ?? 0) + 1)
    }
    return m
  }, [paneEvents])

  /** Live count of hazard events per disaster type on this pane. */
  const typeCounts = useMemo(() => {
    const m = new Map<HazardTypeKey, number>()
    for (const ev of paneEvents) {
      if (ev.category !== "hazard") continue
      const k = hazardKind(ev)
      if (k === "other") continue
      m.set(k as HazardTypeKey, (m.get(k as HazardTypeKey) ?? 0) + 1)
    }
    return m
  }, [paneEvents])

  /** Distinct country codes + their counts on this pane. */
  const countryCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const ev of paneEvents) {
      for (const code of countryCodesForEvent(ev)) {
        m.set(code, (m.get(code) ?? 0) + 1)
      }
    }
    return m
  }, [paneEvents])

  const distinctCountries = useMemo(() => {
    return Array.from(countryCounts.keys()).sort()
  }, [countryCounts])

  const paneTotal = paneEvents.length

  //: Said in the panel rather than inferred from an empty map (#—, this PR).
  const exclusions = useMemo(
    () => activeExclusions({ sources, hazardTypes, severity, countries, keyword }),
    [sources, hazardTypes, severity, countries, keyword],
  )
  const everythingHidden = filtersHideEverything(visibleTotal, paneTotal)
  const narrowedSeverity = severityIsNarrowed(severity)

  /** Live count of pane-scoped events matching the current keyword across
   *  source/category/country/keywords/payload — the same fields the global
   *  useEventsInWindow filter scans. */
  const keywordMatches = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return 0
    let n = 0
    for (const ev of paneEvents) {
      const hay = [
        ev.source,
        ev.category,
        ev.country,
        (ev.keywords ?? []).join(" "),
        JSON.stringify(ev.payload ?? {}),
      ]
        .join(" ")
        .toLowerCase()
      if (hay.includes(kw)) n += 1
    }
    return n
  }, [paneEvents, keyword])

  /** Top 5 keyword-matching events for the live preview under the keyword
   *  input in the Filters tab. Same haystack the global filter uses. */
  const keywordPreview = useMemo<EventRow[]>(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return []
    const hits: EventRow[] = []
    for (const ev of paneEvents) {
      const hay = [
        ev.source,
        ev.category,
        ev.country,
        (ev.keywords ?? []).join(" "),
        JSON.stringify(ev.payload ?? {}),
      ]
        .join(" ")
        .toLowerCase()
      if (hay.includes(kw)) hits.push(ev)
      if (hits.length >= 60) break
    }
    return hits
      .sort((a, b) => (b.severity ?? 0) - (a.severity ?? 0))
      .slice(0, 5)
  }, [paneEvents, keyword])

  const activeCount =
    paneFilters.filter((f) => !sources[f.key]).length +
    HAZARD_TYPE_FILTERS.filter((h) => !hazardTypes[h.key]).length +
    (severity[0] > 0 || severity[1] < 1 ? 1 : 0) +
    (countries.length > 0 ? 1 : 0) +
    (keyword.trim() ? 1 : 0) +
    0

  const isLeft = side === "left"

  // Hover open/close: immediate on the way in, patient on the way out (250 ms
  // grace) so the cursor can dip into the panel without it collapsing if you
  // graze the edge.
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  //: Closing by hand beats hovering, until the cursor leaves.
  //:
  //: The panel occupies the pane edge while it is open, so its close control
  //: sits over the ground the collapsed strip returns to. Click it and the
  //: strip re-mounts under a stationary cursor, whose next pixel of movement
  //: is a fresh `mouseenter` — the panel reopens and the close button reads as
  //: broken. A deliberate close therefore suppresses hover-open until the
  //: pointer has actually left the rail, which is the event that proves the
  //: reader moved rather than the UI moving under them.
  const suppressHoverRef = useRef(false)

  const clearTimers = () => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }

  const closeByHand = () => {
    suppressHoverRef.current = true
    clearTimers()
    onOpenChange(false)
  }

  const requestOpen = () => {
    if (suppressHoverRef.current) return
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
    if (open) return
    onOpenChange(true)
  }

  const requestClose = () => {
    if (!open) return
    closeTimerRef.current = setTimeout(() => onOpenChange(false), 250)
  }

  useEffect(() => () => clearTimers(), [])

  // Window-level fallback: when the cursor sails toward the very edge of the
  // pane (within 18 px) we open the rail immediately. Catches the case where
  // the user flicks the mouse past the edge faster than the local
  // mouseenter handler can pick it up — common on trackpads + larger screens.
  // 16 px is the size of the wider edge zone, plus a 2 px cushion for cursor
  // hot-spot offset.
  useEffect(() => {
    if (open || hidden) return
    const PROXIMITY_PX = 18
    const handle = (e: MouseEvent) => {
      if (isLeft) {
        if (e.clientX <= PROXIMITY_PX) requestOpen()
      } else {
        if (window.innerWidth - e.clientX <= PROXIMITY_PX) requestOpen()
      }
    }
    window.addEventListener("mousemove", handle, { passive: true })
    return () => window.removeEventListener("mousemove", handle)
    // requestOpen reads `open`, refresh listener when state changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, hidden, isLeft])

  return (
    <div
      className={cn(
        "pointer-events-none absolute bottom-3 top-3 z-20 flex items-stretch gap-2",
        isLeft ? "left-3" : "right-3",
      )}
      onMouseLeave={() => {
        suppressHoverRef.current = false
        requestClose()
      }}
      onMouseEnter={() => {
        if (closeTimerRef.current) {
          clearTimeout(closeTimerRef.current)
          closeTimerRef.current = null
        }
      }}
    >
      {/*: The deck's handle, exactly: it floats on the map *outside* the thing
          it collapses, vertically centred, always there. Because it is the
          first flex child on this side, whatever the rail is showing — the
          icon strip alone, or the strip with the panel open beside it — grows
          away from the handle, and the handle rides along on the outer edge.
          Square corners against what it moves, round corners toward the map.
          The arrow points the way the rail will go. */}
      <button
        type="button"
        aria-label={hidden ? "Show filters" : "Hide filters"}
        aria-expanded={!hidden}
        title={hidden ? "Show filters" : "Hide filters"}
        onClick={() => {
          if (!hidden) closeByHand()
          setHidden(!hidden)
        }}
        className={cn(
          "pointer-events-auto my-auto shrink-0 border border-white/10 bg-neutral-950/85 px-1.5 py-6 text-neutral-400 shadow-2xl shadow-black/60 backdrop-blur-xl transition-colors hover:text-neutral-100",
          isLeft ? "order-last rounded-l-md rounded-r-xl" : "order-first rounded-l-xl rounded-r-md",
        )}
      >
        {isLeft === hidden ? (
          <ChevronRight size={16} aria-hidden />
        ) : (
          <ChevronLeft size={16} aria-hidden />
        )}
      </button>

      {/* Edge hover zone: a 16 px transparent column at the pane edge requests
       *  open the moment the cursor enters. Wider than before (was 6 px) so a
       *  cursor flicked into the viewport edge still lands on it; mouseenter
       *  is debounce-free so the open feels instant. */}
      {!open && !hidden && (
        <div
          aria-hidden
          className={cn(
            "pointer-events-auto absolute inset-y-0 z-10 w-4",
            isLeft ? "-left-3" : "-right-3",
          )}
          onMouseEnter={requestOpen}
          onPointerEnter={requestOpen}
        />
      )}

      {/* Collapsed icon strip — hovering anywhere on it (the 44 px wide column
       *  with the slider button + colored source dots) opens the rail too,
       *  not just the bare edge cushion. Lets the user mouse over the dots
       *  and have the panel slide out without precision-aiming the edge. */}
      {/*: The strip is the panel's collapsed form, not a second copy of it.
          While the panel is open the right side is the list and nothing else,
          which is the whole point of the redesign. */}
      {!hidden && !open && (
      <div
        className={cn(
          "pointer-events-auto flex w-11 flex-col items-center gap-2 rounded-2xl border border-white/10 bg-neutral-950/85 py-3 shadow-2xl shadow-black/60 backdrop-blur-xl",
          isLeft ? "order-first" : "order-last",
        )}
        onMouseEnter={requestOpen}
        onPointerEnter={requestOpen}
      >
        <button
          type="button"
          aria-label={open ? "Collapse filters" : "Expand filters"}
          aria-expanded={open}
          onClick={() => onOpenChange(!open)}
          className={cn(
            "relative grid h-8 w-8 place-items-center rounded-md border text-neutral-300 transition-colors",
            open
              ? "border-neutral-600 bg-neutral-800 text-neutral-50"
              : "border-neutral-800 hover:border-neutral-600 hover:text-neutral-100",
          )}
        >
          <SlidersHorizontal className="h-4 w-4" />
          {activeCount > 0 && (
            <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-emerald-500 px-1 font-mono text-[10px] font-medium text-neutral-950">
              {activeCount}
            </span>
          )}
        </button>
        {/* Source type icons as quick toggles */}
        {paneFilters.map((f) => {
          const Icon = SOURCE_ICONS[f.key]
          const on = sources[f.key]
          return (
            <button
              key={f.key}
              type="button"
              aria-label={`${f.label} ${on ? "on" : "off"}`}
              aria-pressed={on}
              onClick={() => toggleSource(f.key)}
              className="grid h-8 w-8 place-items-center rounded-md transition-colors hover:bg-neutral-800"
            >
              <span
                className="grid h-5 w-5 place-items-center rounded-md transition-opacity"
                style={{ backgroundColor: f.hex, opacity: on ? 1 : 0.25 }}
              >
                {Icon && <Icon className="h-3 w-3 text-neutral-950" strokeWidth={2.5} />}
              </span>
            </button>
          )
        })}
        {/* Disaster-type quick toggles (map pane) — same set as the expanded
         *  Disasters section, so the collapsed strip shows every filter too. */}
        {HAZARD_TYPE_FILTERS.map((h) => {
            const Icon = HAZARD_TYPE_ICONS[h.key]
            const on = hazardTypes[h.key]
            return (
              <button
                key={h.key}
                type="button"
                aria-label={`${h.label} ${on ? "on" : "off"}`}
                aria-pressed={on}
                onClick={() => toggleHazardType(h.key)}
                className="grid h-8 w-8 place-items-center rounded-md transition-colors hover:bg-neutral-800"
              >
                <span
                  className="grid h-5 w-5 place-items-center rounded-md transition-opacity"
                  style={{ backgroundColor: h.hex, opacity: on ? 1 : 0.25 }}
                >
                  <Icon className="h-3 w-3 text-neutral-950" strokeWidth={2.5} />
                </span>
              </button>
            )
          })}
      </div>
      )}

      {/* The panel: one list, nothing else.
       *
       * It used to be a stack of differently-shaped blocks — bordered cards
       * for sources, more cards for disasters, loose controls under them —
       * which made a short list of toggles read as five unrelated widgets.
       * Now it is one scroll: a summary of what is on the map, then grouped
       * rows in inset containers, hairlines between them, the group caption
       * the only thing outside the container. Everything on this side of the
       * console filters the map, and nothing on this side does anything else.
       */}
      {open && !hidden && (
        <div className="pointer-events-auto flex w-[330px] flex-col overflow-y-auto rounded-2xl border border-white/10 bg-neutral-950/85 shadow-2xl shadow-black/60 backdrop-blur-xl">
          {/*: The header answers the question a map raises — what am I looking
              at — and answers it from the events that survived the filters, so
              it can never disagree with the markers. The buffer count stays,
              small, because "6,154 of 7,500 held" is the honest frame. */}
          <header className="sticky top-0 z-10 border-b border-white/5 bg-neutral-950/90 px-4 pb-3 pt-3.5 backdrop-blur-xl">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
                  On the map
                </p>
                <p className="mt-1 flex items-baseline gap-1.5">
                  <span className="text-[26px] font-medium leading-none tabular-nums text-neutral-50">
                    {visibleTotal.toLocaleString()}
                  </span>
                  {/*: Two quantities, named — not "of N", which would blame
                      the filters for what the time window did. The buffer
                      spans days; the map shows one window of it. */}
                  <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">
                    shown · {paneTotal.toLocaleString()} buffered
                  </span>
                </p>
              </div>
              <button
                type="button"
                aria-label="Close panel"
                onClick={closeByHand}
                className="-mr-1 -mt-1 rounded-md p-1 text-neutral-600 transition-colors hover:bg-white/5 hover:text-neutral-200"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {summaryChips.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-1">
                {summaryChips.map((chip) => (
                  <span
                    key={chip.key}
                    className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] py-0.5 pl-1.5 pr-2"
                  >
                    <span
                      aria-hidden
                      className="h-1.5 w-1.5 rounded-full"
                      style={{ backgroundColor: chip.hex }}
                    />
                    <span className="font-mono text-[10px] tabular-nums text-neutral-100">
                      {chip.count.toLocaleString()}
                    </span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">
                      {chip.label}
                    </span>
                  </span>
                ))}
              </div>
            )}

            {/*: What is being excluded, and by which control. Every filter here
                can empty the map, and the severity range can do it from one
                stray click on its track — which looks exactly like the map
                breaking. */}
            {exclusions.length > 0 && (
              <p className="mt-2 font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                {exclusions.join(" · ")}
              </p>
            )}
          </header>

          <div className="flex flex-col gap-5 px-4 pb-4 pt-4">
            {/*: An empty map and a broken map look alike, so the one case that
                is neither gets said out loud, with the way back attached. */}
            {everythingHidden && (
              <button
                type="button"
                onClick={reset}
                className="flex items-center gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-left font-mono text-[10px] uppercase tracking-wider text-amber-200/90 transition-colors hover:border-amber-400/70"
              >
                <RotateCcw className="h-3.5 w-3.5 shrink-0" />
                <span>filters hide all {paneTotal.toLocaleString()} events — reset</span>
              </button>
            )}

            <section>
              <GroupCaption
                label="Sources"
                onAll={() => setAllSources(true)}
                onNone={() => setAllSources(false)}
              />
              <ListGroup>
                {paneFilters.map((f) => (
                  <ToggleRow
                    key={f.key}
                    icon={SOURCE_ICONS[f.key]}
                    hex={f.hex}
                    label={f.label}
                    count={sourceCounts.get(f.key) ?? 0}
                    on={sources[f.key]}
                    onToggle={() => toggleSource(f.key)}
                  />
                ))}
              </ListGroup>
            </section>

            <section>
              <GroupCaption
                label="Disasters"
                onAll={() => setAllHazardTypes(true)}
                onNone={() => setAllHazardTypes(false)}
              />
              <ListGroup>
                {HAZARD_TYPE_FILTERS.map((h) => (
                  <ToggleRow
                    key={h.key}
                    icon={HAZARD_TYPE_ICONS[h.key]}
                    hex={h.hex}
                    label={h.label}
                    count={typeCounts.get(h.key) ?? 0}
                    on={hazardTypes[h.key]}
                    onToggle={() => toggleHazardType(h.key)}
                  />
                ))}
              </ListGroup>
            </section>

            <section>
              <GroupCaption label="Refine" />
              <ListGroup>
                {/* Severity */}
                <div className="px-3 py-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] text-neutral-200">Severity</span>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "font-mono text-[11px] tabular-nums",
                          narrowedSeverity ? "text-amber-300/90" : "text-neutral-400",
                        )}
                      >
                        {severity[0].toFixed(2)} – {severity[1].toFixed(2)}
                      </span>
                      {/*: The track moves the nearest thumb wherever it is
                          clicked, so this range narrows by accident more than
                          by intent. One click puts it back without resetting
                          anything else. */}
                      {narrowedSeverity && (
                        <button
                          type="button"
                          onClick={() => setSeverity([...FULL_SEVERITY])}
                          className="rounded px-1 py-0.5 font-mono text-[9px] uppercase tracking-wider text-neutral-400 hover:bg-white/10 hover:text-neutral-100"
                        >
                          all
                        </button>
                      )}
                    </div>
                  </div>
                  <Slider
                    className="mt-3"
                    value={severity}
                    min={0}
                    max={1}
                    step={0.01}
                    onValueChange={(v) => {
                      if (Array.isArray(v)) setSeverity([v[0], v[1]])
                    }}
                    aria-label="Severity range"
                  />
                </div>

                {/* Country */}
                <div className="px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] text-neutral-200">Country</span>
                    <Popover open={countryOpen} onOpenChange={setCountryOpen}>
                      <PopoverTrigger
                        render={
                          <Button
                            variant="ghost"
                            role="combobox"
                            aria-expanded={countryOpen}
                            className="h-7 gap-1.5 px-2 font-mono text-[11px] text-neutral-300 hover:bg-white/10 hover:text-neutral-100"
                          />
                        }
                      >
                        {countries.length > 0 ? `${countries.length} selected` : "All"}
                        <ChevronsUpDown className="h-3 w-3 opacity-50" />
                      </PopoverTrigger>
                      <PopoverContent
                        align="end"
                        className="w-[248px] border-neutral-700 bg-neutral-900 p-0"
                      >
                        <Command className="bg-neutral-900">
                          <CommandInput placeholder="Search country or ISO…" className="text-xs" />
                          <CommandList className="max-h-72">
                            <CommandEmpty className="py-4 text-center text-xs text-neutral-500">
                              No country found.
                            </CommandEmpty>
                            <CommandGroup>
                              {[...distinctCountries]
                                .sort(
                                  (a, b) => (countryCounts.get(b) ?? 0) - (countryCounts.get(a) ?? 0),
                                )
                                .map((c) => {
                                  const flag = countryFlagEmoji(c)
                                  const name = countryDisplayName(c)
                                  const n = countryCounts.get(c) ?? 0
                                  // cmdk filters on value, so concatenate ISO +
                                  // name so typing 'pak' matches PK / Pakistan.
                                  const value = `${c} ${name}`
                                  return (
                                    <CommandItem
                                      key={c}
                                      value={value}
                                      onSelect={() => toggleCountry(c)}
                                      className="flex items-center gap-2 font-mono text-xs"
                                    >
                                      <Check
                                        className={cn(
                                          "h-3.5 w-3.5",
                                          countries.includes(c) ? "opacity-100" : "opacity-0",
                                        )}
                                      />
                                      <span className="w-5">{flag}</span>
                                      <span className="w-7 text-neutral-300">{c}</span>
                                      <span className="flex-1 truncate text-[11px] text-neutral-400">
                                        {name}
                                      </span>
                                      <span className="tabular-nums text-[10px] text-neutral-500">
                                        {n.toLocaleString()}
                                      </span>
                                    </CommandItem>
                                  )
                                })}
                            </CommandGroup>
                          </CommandList>
                        </Command>
                      </PopoverContent>
                    </Popover>
                  </div>
                  {countries.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {countries.map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => toggleCountry(c)}
                          className="flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 font-mono text-[10px] text-neutral-300 hover:bg-white/20"
                        >
                          {c}
                          <X className="h-2.5 w-2.5" />
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Keyword */}
                <div className="px-3 py-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] text-neutral-200">Keyword</span>
                    {keyword.trim() && (
                      <span className="font-mono text-[10px] tabular-nums text-neutral-500">
                        {keywordMatches.toLocaleString()} match
                        {keywordMatches === 1 ? "" : "es"}
                      </span>
                    )}
                  </div>
                  <div className="relative mt-2">
                    <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-neutral-600" />
                    <Input
                      value={keyword}
                      onChange={(e) => setKeyword(e.target.value)}
                      placeholder="protest, fire, USGS, drawdown…"
                      className="h-8 border-white/10 bg-white/[0.04] pl-8 font-mono text-xs text-neutral-200 placeholder:text-neutral-600"
                    />
                  </div>
                  {/*: Live preview: the dataset shaping in real time, so a
                      keyword that matches nothing is obvious before it is
                      blamed on the map. */}
                  {keyword.trim() && keywordPreview.length > 0 && (
                    <div className="mt-2 flex flex-col gap-0.5">
                      {keywordPreview.map((ev) => {
                        const sev = typeof ev.severity === "number" ? ev.severity : 0
                        const when = formatDistanceToNowStrict(new Date(ev.occurred_at), {
                          addSuffix: false,
                        })
                        return (
                          <div
                            key={ev.id}
                            className="flex items-center gap-2 rounded-md px-1 py-1 text-[11px] hover:bg-white/5"
                            title={`${ev.source} · sev ${sev.toFixed(2)} · ${when} ago`}
                          >
                            <span
                              className="inline-block h-3 w-1 shrink-0 rounded-sm"
                              style={{ backgroundColor: severityBarColor(sev) }}
                            />
                            <span className="w-5 shrink-0 text-center" aria-label={ev.country ?? ""}>
                              {ev.country ? countryFlagEmoji(ev.country) : "—"}
                            </span>
                            <span className="flex-1 truncate text-neutral-300">
                              {eventListTitle(ev)}
                            </span>
                            <span className="shrink-0 font-mono text-[9px] tabular-nums text-neutral-600">
                              {when}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  )}
                  {keyword.trim() && keywordPreview.length === 0 && (
                    <p className="mt-2 font-mono text-[10px] text-neutral-600">
                      Nothing in the window matches this keyword.
                    </p>
                  )}
                </div>
              </ListGroup>
            </section>

            {/*: Last, and its own group: the backdrop and the live layer are
                not filters — they add to the map rather than subtracting from
                it — but they are still things the map is showing, so this is
                where they belong. */}
            <section>
              <GroupCaption label="Backdrop" note={activeImagery ? imageryDay : undefined} />
              <ListGroup>
                {IMAGERY_LAYERS.map((layer) => (
                  <ToggleRow
                    key={layer.id}
                    label={layer.label}
                    hint={layer.hint}
                    on={activeImagery === layer.id}
                    onToggle={() => toggleImagery(layer.id)}
                  />
                ))}
                <ToggleRow
                  label="Military air"
                  hint={
                    presenceAtNow
                      ? "military and distress squawks, live"
                      : "live only — scrub back to now"
                  }
                  on={presenceOn}
                  disabled={!presenceAtNow}
                  onToggle={togglePresence}
                />
              </ListGroup>
              {activeImagery && imageryMissing && (
                <p className="mt-1.5 px-1 font-mono text-[10px] uppercase tracking-wider text-amber-300/80">
                  no imagery for {imageryDay}
                </p>
              )}
              {activeImagery && (
                <p className="mt-1 px-1 font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                  NASA GIBS · Worldview
                </p>
              )}
              {presenceOn && presenceAtNow && (
                <p className="mt-1 px-1 font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                  adsb.lol · ODbL
                </p>
              )}
            </section>

            <Button
              variant="ghost"
              onClick={reset}
              className="h-8 justify-center gap-2 text-xs text-neutral-500 hover:bg-white/5 hover:text-neutral-100"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset filters
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
