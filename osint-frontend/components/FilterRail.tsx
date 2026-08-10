"use client"

import { useMemo, useState } from "react"
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
  //: Severity, country and keyword are not layers — they cannot be read off
  //: the map the way a switched-off source can, and inline they turned a list
  //: of layers into a form. Folded away by default, one click from open.
  const [moreOpen, setMoreOpen] = useState(false)

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
  const { total: visibleTotal } = useEventsInWindow(useStore, supplementalEvents)

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

  return (
    <div
      className={cn(
        "pointer-events-none absolute bottom-3 top-3 z-20 flex items-stretch gap-2",
        isLeft ? "left-3" : "right-3",
      )}
    >
      {/*: The deck's handle, exactly: it floats on the map *outside* the thing
          it collapses, vertically centred, always there. Because it is the
          first flex child on this side, the panel grows away from the handle
          and the handle rides along on the outer edge. Square corners against
          what it moves, round corners toward the map. The arrow points the way
          the panel will go. */}
      <button
        type="button"
        aria-label={open ? "Hide filters" : "Show filters"}
        aria-expanded={open}
        title={open ? "Hide filters" : "Show filters"}
        onClick={() => onOpenChange(!open)}
        className={cn(
          "pointer-events-auto relative my-auto shrink-0 border border-white/10 bg-neutral-950/85 px-1.5 py-6 text-neutral-400 shadow-2xl shadow-black/60 backdrop-blur-xl transition-colors hover:text-neutral-100",
          isLeft ? "order-last rounded-l-md rounded-r-xl" : "order-first rounded-l-xl rounded-r-md",
        )}
      >
        {isLeft === !open ? (
          <ChevronRight size={16} aria-hidden />
        ) : (
          <ChevronLeft size={16} aria-hidden />
        )}
        {/*: Put away, the panel takes every filter with it. The count rides
            the handle so a map narrowed by an earlier click still says so. */}
        {!open && activeCount > 0 && (
          <span className="absolute -left-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-emerald-500 px-1 font-mono text-[10px] font-medium text-neutral-950">
            {activeCount}
          </span>
        )}
      </button>

      {/*: One panel, not a panel and a strip of the same switches beside it.
          Every layer is a row in the list below; the strip said the same
          things in icons, in a column the map had to make room for. */}
      {open && (
        <div
          className={cn(
            "pointer-events-auto flex w-[280px] flex-col gap-4 overflow-y-auto rounded-2xl border border-white/10 bg-neutral-950/85 p-4 shadow-2xl shadow-black/60 backdrop-blur-xl",
          )}
        >
          <div className="flex items-center justify-between">
            <div className="flex flex-col">
              <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                Map · {paneTotal.toLocaleString()} pane / {visibleTotal.toLocaleString()} in window
              </span>
              {/*: What is being excluded, and by which control. Every filter
                  here can empty the map, and the severity range can do it from
                  one stray click on its track — which looks exactly like the
                  map breaking. */}
              {exclusions.length > 0 && (
                <span className="mt-0.5 font-mono text-[9px] uppercase tracking-wider text-neutral-500">
                  {exclusions.join(" · ")}
                </span>
              )}
            </div>
            <button
              type="button"
              aria-label="Close panel"
              onClick={() => onOpenChange(false)}
              className="text-neutral-500 hover:text-neutral-200"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/*: An empty map and a broken map look alike, so the one case that
              is neither gets said out loud, with the way back attached. */}
          {everythingHidden && (
            <button
              type="button"
              onClick={reset}
              className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-amber-200/90 transition-colors hover:border-amber-400/70"
            >
              <RotateCcw className="h-3.5 w-3.5 shrink-0" />
              <span>
                filters hide all {paneTotal.toLocaleString()} events — reset
              </span>
            </button>
          )}

          {/* Source toggles — every source on by default; click one to hide it
           *  (e.g. mute the quakes when they crowd the map). Select-all /
           *  clear-all flip them in one go. */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between px-0.5">
              <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                Layers
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setAllSources(true)}
                  className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                >
                  All
                </button>
                <span className="text-neutral-700">·</span>
                <button
                  type="button"
                  onClick={() => setAllSources(false)}
                  className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                >
                  None
                </button>
              </div>
            </div>
            {paneFilters.map((f) => {
              const n = sourceCounts.get(f.key) ?? 0
              const Icon = SOURCE_ICONS[f.key]
              const on = sources[f.key]
              return (
                <button
                  key={f.key}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggleSource(f.key)}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md border px-2.5 py-2 text-left text-[13px] transition-colors",
                    on
                      ? "border-neutral-700 bg-neutral-800/60 text-neutral-100"
                      : "border-neutral-800/60 text-neutral-500 hover:border-neutral-700",
                  )}
                >
                  <span
                    className="grid h-6 w-6 shrink-0 place-items-center rounded-md transition-opacity"
                    style={{ backgroundColor: f.hex, opacity: on ? 1 : 0.25 }}
                  >
                    {Icon && <Icon className="h-3.5 w-3.5 text-neutral-950" strokeWidth={2.5} />}
                  </span>
                  <span className="flex-1">{f.label}</span>
                  <span className="font-mono text-[10px] tabular-nums text-neutral-400">
                    {n.toLocaleString()}
                  </span>
                  <span
                    className={cn(
                      "grid h-4 w-4 shrink-0 place-items-center rounded-sm border",
                      on ? "border-emerald-500 bg-emerald-500/20" : "border-neutral-700",
                    )}
                  >
                    {on && <Check className="h-3 w-3 text-emerald-400" strokeWidth={3} />}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Satellite backdrop (#875). One at a time, off by default: two
           *  rasters stacked on a dark style is mud, and the map's ordinary
           *  appearance is not up for renegotiation as a side effect of adding
           *  an option. The day shown is the scrubber's day, said out loud so
           *  the backdrop can never quietly disagree with the markers. */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between px-0.5">
              <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                Satellite
              </span>
              <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-600">
                {imageryDay}
              </span>
            </div>
            {IMAGERY_LAYERS.map((layer) => {
              const on = activeImagery === layer.id
              return (
                <button
                  key={layer.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggleImagery(layer.id)}
                  className={cn(
                    "flex flex-col gap-0.5 rounded-md border px-2.5 py-2 text-left transition-colors",
                    on
                      ? "border-neutral-700 bg-neutral-800/60 text-neutral-100"
                      : "border-neutral-800/60 text-neutral-500 hover:border-neutral-700",
                  )}
                >
                  <span className="text-[13px]">{layer.label}</span>
                  <span className="font-mono text-[10px] text-neutral-600">{layer.hint}</span>
                </button>
              )
            })}
            {/* A gap in the archive is normal — whole days are absent from a
             *  record that otherwise reaches back years. A blank backdrop with
             *  no explanation reads as a broken map, so it is named. */}
            {activeImagery && imageryMissing && (
              <span className="px-0.5 font-mono text-[10px] uppercase tracking-wider text-amber-300/80">
                no imagery for {imageryDay}
              </span>
            )}
            {activeImagery && (
              <span className="px-0.5 font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                NASA GIBS · Worldview
              </span>
            )}
          </div>

          {/* Live aircraft (#873). Not events: these never enter the counts,
           *  the source filters, the clustering or the situation list. */}
          <div className="flex flex-col gap-1.5">
            <span className="px-0.5 font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Live
            </span>
            <button
              type="button"
              aria-pressed={presenceOn}
              disabled={!presenceAtNow}
              onClick={togglePresence}
              className={cn(
                "flex flex-col gap-0.5 rounded-md border px-2.5 py-2 text-left transition-colors",
                !presenceAtNow
                  ? "cursor-not-allowed border-neutral-800/40 text-neutral-700"
                  : presenceOn
                    ? "border-neutral-700 bg-neutral-800/60 text-neutral-100"
                    : "border-neutral-800/60 text-neutral-500 hover:border-neutral-700",
              )}
            >
              <span className="text-[13px]">Military air</span>
              <span className="font-mono text-[10px] text-neutral-600">
                {presenceAtNow
                  ? "military and distress squawks, live"
                  : "live only \u2014 scrub back to now"}
              </span>
            </button>
            {presenceOn && presenceAtNow && (
              <span className="px-0.5 font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                adsb.lol \u00b7 ODbL
              </span>
            )}
          </div>

          {/* Disaster types — replaces the single GDACS "multi-hazard" switch so
           *  each disaster (earthquake / cyclone / flood / volcano / drought /
           *  wildfire) can be hidden on its own. */}
          {(
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between px-0.5">
                <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                  Disasters
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setAllHazardTypes(true)}
                    className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                  >
                    All
                  </button>
                  <span className="text-neutral-700">·</span>
                  <button
                    type="button"
                    onClick={() => setAllHazardTypes(false)}
                    className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                  >
                    None
                  </button>
                </div>
              </div>
              {HAZARD_TYPE_FILTERS.map((h) => {
                const Icon = HAZARD_TYPE_ICONS[h.key]
                const on = hazardTypes[h.key]
                const n = typeCounts.get(h.key) ?? 0
                return (
                  <button
                    key={h.key}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggleHazardType(h.key)}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md border px-2.5 py-2 text-left text-[13px] transition-colors",
                      on
                        ? "border-neutral-700 bg-neutral-800/60 text-neutral-100"
                        : "border-neutral-800/60 text-neutral-500 hover:border-neutral-700",
                    )}
                  >
                    <span
                      className="grid h-6 w-6 shrink-0 place-items-center rounded-md transition-opacity"
                      style={{ backgroundColor: h.hex, opacity: on ? 1 : 0.25 }}
                    >
                      <Icon className="h-3.5 w-3.5 text-neutral-950" strokeWidth={2.5} />
                    </span>
                    <span className="flex-1">{h.label}</span>
                    <span className="font-mono text-[10px] tabular-nums text-neutral-400">
                      {n.toLocaleString()}
                    </span>
                    <span
                      className={cn(
                        "grid h-4 w-4 shrink-0 place-items-center rounded-sm border",
                        on ? "border-emerald-500 bg-emerald-500/20" : "border-neutral-700",
                      )}
                    >
                      {on && <Check className="h-3 w-3 text-emerald-400" strokeWidth={3} />}
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {/*: Severity, country and keyword are not layers. A layer that is
              off can be read off the map; a narrowed severity range or a
              keyword cannot, and inline they turned a list of layers into a
              form. Folded away, one click from open, and the header above
              still says when one of them is hiding something. */}
          <div className="flex flex-col gap-3 border-t border-neutral-800 pt-3">
            <button
              type="button"
              aria-expanded={moreOpen}
              onClick={() => setMoreOpen(!moreOpen)}
              className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-neutral-400 transition-colors hover:text-neutral-100"
            >
              <ChevronRight
                className={cn("h-3 w-3 shrink-0 transition-transform", moreOpen && "rotate-90")}
                aria-hidden
              />
              More filters
              {!moreOpen && (
                <span className="ml-auto text-[9px] tracking-wider text-neutral-600">
                  severity · country · keyword
                </span>
              )}
            </button>
            {moreOpen && (
              <>
              {/* Severity */}
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                    Severity
                  </span>
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "font-mono text-[11px]",
                        narrowedSeverity ? "text-amber-300/90" : "text-neutral-300",
                      )}
                    >
                      {severity[0].toFixed(2)} – {severity[1].toFixed(2)}
                    </span>
                    {/*: The track moves the nearest thumb wherever it is clicked,
                        so this range narrows by accident more than by intent. One
                        click puts it back without resetting anything else. */}
                    {narrowedSeverity && (
                      <button
                        type="button"
                        onClick={() => setSeverity([...FULL_SEVERITY])}
                        className="rounded px-1 py-0.5 font-mono text-[9px] uppercase tracking-wider text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                      >
                        all
                      </button>
                    )}
                  </div>
                </div>
                <Slider
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

              {/* Country multiselect */}
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                    Country
                  </span>
                  <span className="font-mono text-[10px] tabular-nums text-neutral-500">
                    {distinctCountries.length.toLocaleString()} known
                  </span>
                </div>
                <Popover open={countryOpen} onOpenChange={setCountryOpen}>
                  <PopoverTrigger
                    render={
                      <Button
                        variant="outline"
                        role="combobox"
                        aria-expanded={countryOpen}
                        className="h-9 justify-between border-neutral-700 bg-neutral-900 font-mono text-xs text-neutral-200 hover:bg-neutral-800 hover:text-neutral-100"
                      />
                    }
                  >
                    {countries.length > 0 ? `${countries.length} selected` : "All countries"}
                    <ChevronsUpDown className="h-3.5 w-3.5 opacity-50" />
                  </PopoverTrigger>
                  <PopoverContent
                    align="start"
                    className="w-[248px] border-neutral-700 bg-neutral-900 p-0"
                  >
                    <Command className="bg-neutral-900">
                      <CommandInput
                        placeholder="Search country or ISO…"
                        className="text-xs"
                      />
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
                              // cmdk filters on value, so concatenate ISO + name so
                              // typing 'pak' matches PK / Pakistan.
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
                {countries.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {countries.map((c) => (
                      <button
                        key={c}
                        type="button"
                        onClick={() => toggleCountry(c)}
                        className="flex items-center gap-1 rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px] text-neutral-300 hover:bg-neutral-700"
                      >
                        {c}
                        <X className="h-2.5 w-2.5" />
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Keyword */}
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                    Keyword
                  </span>
                  {keyword.trim() && (
                    <span className="font-mono text-[10px] tabular-nums text-neutral-500">
                      {keywordMatches.toLocaleString()} match
                      {keywordMatches === 1 ? "" : "es"}
                    </span>
                  )}
                </div>
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-neutral-500" />
                  <Input
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    placeholder="Try: protest, fire, USGS, drawdown…"
                    className="h-9 border-neutral-700 bg-neutral-900 pl-8 font-mono text-xs text-neutral-200 placeholder:text-neutral-600"
                  />
                </div>
                <p className="font-mono text-[10px] leading-snug text-neutral-500">
                  Searches event source, category, country, keywords + payload values.
                </p>

                {/* Live preview: top matches against the current keyword. Sits
                 *  under the helper text in the Filters tab so the user can see
                 *  the dataset shaping in real time without flipping to Events. */}
                {keyword.trim() && keywordPreview.length > 0 && (
                  <div className="mt-1 flex flex-col gap-0.5 rounded-md border border-neutral-800 bg-neutral-900/50 p-1">
                    <div className="flex items-center justify-between px-1 pb-0.5">
                      <span className="font-mono text-[9px] uppercase tracking-widest text-neutral-500">
                        Top matches
                      </span>
                    </div>
                    {keywordPreview.map((ev) => {
                      const sev = typeof ev.severity === "number" ? ev.severity : 0
                      const when = formatDistanceToNowStrict(new Date(ev.occurred_at), {
                        addSuffix: false,
                      })
                      return (
                        <div
                          key={ev.id}
                          className="flex items-center gap-2 rounded px-1.5 py-1 text-[11px] hover:bg-neutral-800"
                          title={`${ev.source} · sev ${sev.toFixed(2)} · ${when} ago`}
                        >
                          <span
                            className="inline-block h-3 w-1 shrink-0 rounded-sm"
                            style={{ backgroundColor: severityBarColor(sev) }}
                          />
                          <span className="w-7 shrink-0 text-center" aria-label={ev.country ?? ""}>
                            {ev.country ? countryFlagEmoji(ev.country) : "—"}
                          </span>
                          <span className="flex-1 truncate text-neutral-200">
                            {eventListTitle(ev)}
                          </span>
                          <span className="shrink-0 font-mono text-[9px] tabular-nums text-neutral-500">
                            {when}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )}
                {keyword.trim() && keywordPreview.length === 0 && (
                  <p className="rounded-md border border-neutral-800 bg-neutral-900/50 p-2 text-center font-mono text-[10px] text-neutral-600">
                    No events match this keyword in the current pane window.
                  </p>
                )}
              </div>

              <Button
                variant="ghost"
                onClick={reset}
                className="mt-auto h-8 justify-center gap-2 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset filters
              </Button>
              </>
            )}
          </div>

        </div>
      )}
    </div>
  )
}
