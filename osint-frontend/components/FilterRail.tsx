"use client"

import { useMemo } from "react"
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Droplets,
  Flame,
  Landmark,
  Layers,
  type LucideIcon,
  Mountain,
  Newspaper,
  Plane,
  RotateCcw,
  ShieldAlert,
  Snowflake,
  Sun,
  TrendingUp,
  Triangle,
  Wind,
} from "lucide-react"
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
  type SourceFilterDef,
  type SourceKey,
} from "@/lib/types"
import { hazardKind } from "@/lib/hazardSymbols"
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
import { Slider } from "@/components/ui/slider"

/** Per-source mark. Monochrome on purpose: eleven saturated chips competing
 *  with a map full of coloured pins is two legends arguing. Colour is spent
 *  where it carries meaning — the disaster rows, whose swatch is the mark the
 *  map actually draws. */
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

/** Which group a source row belongs to. The panel is read top to bottom, so
 *  rows are grouped by what they are rather than by which API they came from. */
function sourceGroup(f: SourceFilterDef): "reporting" | "markets" {
  return f.category === "market" ? "markets" : "reporting"
}

interface FilterRailProps {
  side: "left" | "right"
  useStore: FilterStore
  open: boolean
  onOpenChange: (open: boolean) => void
  supplementalEvents?: EventRow[]
}

const NO_SUPPLEMENTAL_EVENTS: EventRow[] = []

/** Small-caps label above a card. The All/None pair or a date rides the right. */
function GroupLabel({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between px-1 pb-1">
      <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
        {children}
      </span>
      {right}
    </div>
  )
}

/** One card per group, hairlines between rows — the rows belong together and
 *  the eye should not have to assemble that from a dozen floating boxes. */
function GroupCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="divide-y divide-white/5 overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
      {children}
    </div>
  )
}

/**
 * One line, one thing that can be on the map.
 *
 * Off is a dimmed row, on is a row with a tick — no checkbox chrome per line,
 * because a column of checkboxes reads as a form to fill in rather than a list
 * of what is showing.
 */
function ToggleRow({
  icon: Icon,
  swatch,
  label,
  count,
  hint,
  on,
  disabled,
  onClick,
}: {
  icon: LucideIcon
  /** Hex for the disaster rows, whose colour is the map's colour. */
  swatch?: string
  label: string
  count?: number
  hint?: string
  on: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 px-2.5 py-1.5 text-left transition-colors",
        disabled ? "cursor-not-allowed" : "hover:bg-white/[0.04]",
      )}
    >
      {swatch ? (
        <span
          className="grid h-4 w-4 shrink-0 place-items-center rounded transition-opacity"
          style={{ backgroundColor: swatch, opacity: on ? 1 : 0.3 }}
        >
          <Icon className="h-2.5 w-2.5 text-neutral-950" strokeWidth={2.5} aria-hidden />
        </span>
      ) : (
        <Icon
          className={cn(
            "h-3.5 w-3.5 shrink-0",
            disabled ? "text-neutral-700" : on ? "text-neutral-300" : "text-neutral-600",
          )}
          strokeWidth={1.75}
          aria-hidden
        />
      )}
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block truncate text-[12px] leading-tight",
            disabled ? "text-neutral-600" : on ? "text-neutral-200" : "text-neutral-500",
          )}
        >
          {label}
        </span>
        {hint && (
          <span className="block truncate font-mono text-[9px] leading-tight text-neutral-600">
            {hint}
          </span>
        )}
      </span>
      {count !== undefined && (
        <span
          className={cn(
            "shrink-0 font-mono text-[10px] tabular-nums",
            on ? "text-neutral-500" : "text-neutral-700",
          )}
        >
          {count.toLocaleString()}
        </span>
      )}
      <Check
        className={cn(
          "h-3.5 w-3.5 shrink-0 transition-opacity",
          on ? "text-emerald-400 opacity-100" : "opacity-0",
        )}
        strokeWidth={3}
        aria-hidden
      />
    </button>
  )
}

/** All / None for one group. Scoped to the rows that group lists — a "none"
 *  reaching rows the reader cannot see empties the map by surprise. */
function AllNone({ onAll, onNone }: { onAll: () => void; onNone: () => void }) {
  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        onClick={onAll}
        className="rounded px-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500 hover:text-neutral-200"
      >
        All
      </button>
      <span className="text-neutral-700">·</span>
      <button
        type="button"
        onClick={onNone}
        className="rounded px-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500 hover:text-neutral-200"
      >
        None
      </button>
    </span>
  )
}

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
  const toggleSource = useStore((s) => s.toggleSource)
  const setAllSources = useStore((s) => s.setAllSources)
  const hazardTypes = useStore((s) => s.hazardTypes)
  const toggleHazardType = useStore((s) => s.toggleHazardType)
  const setAllHazardTypes = useStore((s) => s.setAllHazardTypes)
  const setSeverity = useStore((s) => s.setSeverity)
  const reset = useStore((s) => s.reset)

  //: The backdrop reads the same clock the markers do (#875).
  const activeImagery = useImageryStore((s) => s.active)
  const imageryMissing = useImageryStore((s) => s.missing)
  const toggleImagery = useImageryStore((s) => s.toggle)
  const windowEndOffsetMs = useStore((s) => s.windowEndOffsetMs)
  const imageryDay = imageryDate(Date.now() - windowEndOffsetMs)

  //: Live aircraft (#873). Disabled rather than hidden when the scrubber
  //: leaves "now": nothing about presence is stored, so there is no past to
  //: show, and a live layer over an old map would read as history.
  const presenceOn = usePresenceStore((st) => st.aircraft)
  const togglePresence = usePresenceStore((st) => st.toggleAircraft)
  const presenceAtNow = windowIsNow(windowEndOffsetMs)

  /** Windowed count for the panel header — the same pipeline the map markers
   *  use, so the header and the dots always agree. */
  const { total: visibleTotal } = useEventsInWindow(useStore, supplementalEvents)

  /** Source toggles, minus the hazard sources (USGS / GDACS / EONET) — those
   *  are filtered by disaster type instead, below. */
  const paneFilters = useMemo(
    () => SOURCE_FILTERS.filter((f) => !HAZARD_SOURCE_KEYS.includes(f.key)),
    [],
  )
  /** Exactly the keys the source groups' All / None may touch. */
  const paneSourceKeys = useMemo(() => paneFilters.map((f) => f.key), [paneFilters])
  const reportingFilters = useMemo(
    () => paneFilters.filter((f) => sourceGroup(f) === "reporting"),
    [paneFilters],
  )
  const marketFilters = useMemo(
    () => paneFilters.filter((f) => sourceGroup(f) === "markets"),
    [paneFilters],
  )

  /** Events that could appear on the map: anything with a known source key.
   *  sourceKeyForEvent returns null for feeds with no renderer (NASA FIRMS,
   *  aviation), so they never reach the counts. */
  const paneEvents = useMemo(() => {
    return allEvents.filter((ev) => sourceKeyForEvent(ev) !== null)
  }, [allEvents])

  /** Live count of pane-scoped events per source — drives the per-row counts. */
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

  const paneTotal = paneEvents.length

  //: Said in the panel rather than inferred from an empty map (#902).
  const exclusions = useMemo(
    () => activeExclusions({ sources, hazardTypes, severity }),
    [sources, hazardTypes, severity],
  )
  const everythingHidden = filtersHideEverything(visibleTotal, paneTotal)
  const narrowedSeverity = severityIsNarrowed(severity)

  const activeCount =
    paneFilters.filter((f) => !sources[f.key]).length +
    HAZARD_TYPE_FILTERS.filter((h) => !hazardTypes[h.key]).length +
    (narrowedSeverity ? 1 : 0)

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

      {/*: One panel, one column of lines. Everything that can be on the map is
          a row in a group, and the groups say what the rows are: what is
          reporting, what is moving in markets, what is a disaster, and what is
          painted over the map itself. */}
      {open && (
        <div className="pointer-events-auto flex w-[264px] flex-col gap-3 overflow-y-auto rounded-2xl border border-white/10 bg-neutral-950/85 p-3 shadow-2xl shadow-black/60 backdrop-blur-xl">
          <div className="flex flex-col gap-0.5 px-1">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
                Map
              </span>
              <span className="font-mono text-[10px] tabular-nums text-neutral-500">
                {visibleTotal.toLocaleString()} / {paneTotal.toLocaleString()}
              </span>
            </div>
            {/*: What is being excluded, and by which control. Every filter here
                can empty the map, and the severity range can do it from one
                stray click on its track — which looks exactly like the map
                breaking. */}
            {exclusions.length > 0 && (
              <span className="font-mono text-[9px] uppercase tracking-wider text-neutral-600">
                {exclusions.join(" · ")}
              </span>
            )}
          </div>

          {/*: An empty map and a broken map look alike, so the one case that is
              neither gets said out loud, with the way back attached. */}
          {everythingHidden && (
            <button
              type="button"
              onClick={reset}
              className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-amber-200/90 transition-colors hover:border-amber-400/70"
            >
              <RotateCcw className="h-3 w-3 shrink-0" />
              <span>filters hide all {paneTotal.toLocaleString()} — reset</span>
            </button>
          )}

          <div className="flex flex-col">
            <GroupLabel
              right={
                <AllNone
                  onAll={() => setAllSources(true, paneSourceKeys)}
                  onNone={() => setAllSources(false, paneSourceKeys)}
                />
              }
            >
              Reporting
            </GroupLabel>
            <GroupCard>
              {reportingFilters.map((f) => (
                <ToggleRow
                  key={f.key}
                  icon={SOURCE_ICONS[f.key]}
                  label={f.label}
                  count={sourceCounts.get(f.key) ?? 0}
                  on={sources[f.key]}
                  onClick={() => toggleSource(f.key)}
                />
              ))}
            </GroupCard>
          </div>

          <div className="flex flex-col">
            <GroupLabel>Markets</GroupLabel>
            <GroupCard>
              {marketFilters.map((f) => (
                <ToggleRow
                  key={f.key}
                  icon={SOURCE_ICONS[f.key]}
                  label={f.label}
                  count={sourceCounts.get(f.key) ?? 0}
                  on={sources[f.key]}
                  onClick={() => toggleSource(f.key)}
                />
              ))}
            </GroupCard>
          </div>

          {/*: Disasters keep their colours: these are the only rows whose mark
              is also the mark on the map, and taking the colour out here would
              break the one legend the map has. */}
          <div className="flex flex-col">
            <GroupLabel
              right={
                <AllNone
                  onAll={() => setAllHazardTypes(true)}
                  onNone={() => setAllHazardTypes(false)}
                />
              }
            >
              Disasters
            </GroupLabel>
            <GroupCard>
              {HAZARD_TYPE_FILTERS.map((h) => (
                <ToggleRow
                  key={h.key}
                  icon={HAZARD_TYPE_ICONS[h.key]}
                  swatch={h.hex}
                  label={h.label}
                  count={typeCounts.get(h.key) ?? 0}
                  on={hazardTypes[h.key]}
                  onClick={() => toggleHazardType(h.key)}
                />
              ))}
            </GroupCard>
          </div>

          {/*: Painted over the map rather than plotted on it: one satellite
              backdrop at a time (two rasters on a dark style is mud), and the
              live aircraft layer, which only means anything at "now". */}
          <div className="flex flex-col">
            <GroupLabel
              right={
                <span className="font-mono text-[10px] tabular-nums text-neutral-600">
                  {imageryDay}
                </span>
              }
            >
              Overlays
            </GroupLabel>
            <GroupCard>
              {IMAGERY_LAYERS.map((layer) => (
                <ToggleRow
                  key={layer.id}
                  icon={Layers}
                  label={layer.label}
                  hint={layer.hint}
                  on={activeImagery === layer.id}
                  onClick={() => toggleImagery(layer.id)}
                />
              ))}
              <ToggleRow
                icon={Plane}
                label="Military air"
                hint={presenceAtNow ? "military and distress squawks" : "live only — scrub to now"}
                on={presenceOn && presenceAtNow}
                disabled={!presenceAtNow}
                onClick={togglePresence}
              />
            </GroupCard>
            {/* A gap in the archive is normal — whole days are absent from a
             *  record that otherwise reaches back years. A blank backdrop with
             *  no explanation reads as a broken map, so it is named. */}
            {activeImagery && imageryMissing && (
              <span className="px-1 pt-1 font-mono text-[9px] uppercase tracking-wider text-amber-300/80">
                no imagery for {imageryDay}
              </span>
            )}
            {(activeImagery || (presenceOn && presenceAtNow)) && (
              <span className="px-1 pt-1 font-mono text-[9px] uppercase tracking-wider text-neutral-700">
                {[
                  activeImagery ? "NASA GIBS" : null,
                  presenceOn && presenceAtNow ? "adsb.lol · ODbL" : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            )}
          </div>

          {/*: The one filter here that is not a layer, kept because it is the
              one that can empty the map from a single stray click on its
              track: clicking a two-thumb slider moves the nearest thumb to the
              click. It says its own range and offers the way back beside it. */}
          <div className="flex flex-col gap-1.5 border-t border-white/5 pt-2">
            <div className="flex items-baseline justify-between px-1">
              <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                Severity
              </span>
              <span className="flex items-baseline gap-1.5">
                <span
                  className={cn(
                    "font-mono text-[10px] tabular-nums",
                    narrowedSeverity ? "text-amber-300/90" : "text-neutral-500",
                  )}
                >
                  {severity[0].toFixed(2)}–{severity[1].toFixed(2)}
                </span>
                {narrowedSeverity && (
                  <button
                    type="button"
                    onClick={() => setSeverity([...FULL_SEVERITY])}
                    className="rounded px-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500 hover:text-neutral-200"
                  >
                    All
                  </button>
                )}
              </span>
            </div>
            <div className="px-1">
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
          </div>

          <button
            type="button"
            onClick={reset}
            className="mt-auto flex items-center justify-center gap-1.5 rounded-lg border border-white/10 py-1.5 font-mono text-[10px] uppercase tracking-widest text-neutral-500 transition-colors hover:text-neutral-200"
          >
            <RotateCcw className="h-3 w-3" />
            Reset
          </button>
        </div>
      )}
    </div>
  )
}
