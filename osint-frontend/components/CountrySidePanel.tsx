"use client"

import { formatDistanceToNowStrict } from "date-fns"
import { ExternalLink, X } from "lucide-react"
import { useCountryEvents, useLatestScores } from "@/lib/queries"
import { colorForEvent, scoreTextColor, type EventRow } from "@/lib/types"
import { cn } from "@/lib/utils"

const regionNames =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null

function countryName(iso: string): string {
  try {
    return regionNames?.of(iso) ?? iso
  } catch {
    return iso
  }
}

const Z_DOMAINS: { key: string; label: string }[] = [
  { key: "market", label: "Market" },
  { key: "geopolitical", label: "Geopolitical" },
  { key: "hazard", label: "Hazard" },
]

function ZBar({ label, value }: { label: string; value: number | undefined }) {
  const v = value ?? 0
  const clamped = Math.max(-3, Math.min(3, v))
  const pct = (Math.abs(clamped) / 3) * 50 // half-width
  const positive = clamped >= 0
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 shrink-0 font-mono text-[10px] uppercase tracking-wider text-neutral-500">
        {label}
      </span>
      <div className="relative h-2 flex-1 rounded-full bg-neutral-800">
        <span className="absolute left-1/2 top-0 h-full w-px bg-neutral-600" />
        <span
          className={cn("absolute top-0 h-full rounded-full", positive ? "bg-red-500/70" : "bg-emerald-500/70")}
          style={{
            width: `${pct}%`,
            left: positive ? "50%" : `${50 - pct}%`,
          }}
        />
      </div>
      <span className="w-10 shrink-0 text-right font-mono text-[10px] text-neutral-400">
        {v >= 0 ? "+" : ""}
        {v.toFixed(2)}
      </span>
    </div>
  )
}

function EventRowItem({ ev }: { ev: EventRow }) {
  const url =
    (ev.payload as { source_url?: string; link?: string })?.source_url ??
    (ev.payload as { link?: string })?.link
  const title = eventTitle(ev)
  const Wrapper = url ? "a" : "div"
  return (
    <Wrapper
      {...(url ? { href: url, target: "_blank", rel: "noreferrer" } : {})}
      className={cn(
        "flex items-center gap-2 rounded-md px-2 py-1.5 text-xs",
        url ? "cursor-pointer hover:bg-neutral-800" : "",
      )}
    >
      <span
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: colorForEvent(ev) }}
      />
      <span className="w-16 shrink-0 font-mono text-[10px] text-neutral-500">
        {formatDistanceToNowStrict(new Date(ev.occurred_at), { addSuffix: false })}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-neutral-300">{title}</span>
        <span className="block truncate font-mono text-[9px] uppercase tracking-wider text-neutral-600">
          {ev.source}
        </span>
      </span>
      <span className="font-mono text-[10px] text-neutral-500">
        {typeof ev.severity === "number" ? ev.severity.toFixed(2) : "—"}
      </span>
      {url && <ExternalLink className="h-3 w-3 shrink-0 text-neutral-600" />}
    </Wrapper>
  )
}

function eventTitle(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const source = (ev.source || "").toLowerCase()
  if (source === "acled") {
    const sub = typeof p.sub_event_type === "string" ? p.sub_event_type : null
    const type = typeof p.event_type === "string" ? p.event_type : null
    const loc = typeof p.location === "string" ? p.location : null
    if (sub && loc) return `${sub} · ${loc}`
    if (type && loc) return `${type} · ${loc}`
    if (type) return type
  }
  if (source === "emdat") {
    const type = typeof p.disaster_type === "string" ? p.disaster_type : null
    const subtype = typeof p.disaster_subtype === "string" ? p.disaster_subtype : null
    if (subtype) return subtype
    if (type) return type
  }
  if (source.startsWith("abuse-ch-")) {
    const malware = typeof p.malware === "string" ? p.malware : null
    const threat = typeof p.threat === "string" ? p.threat : null
    const city = typeof p.geo_city === "string" ? p.geo_city : null
    if (malware && city) return `${malware} C2 · ${city}`
    if (threat && city) return `${threat} · ${city}`
    if (malware) return `${malware} C2`
    if (threat) return threat
  }
  const title = typeof p.title === "string" ? p.title : null
  return title ?? ev.source
}

interface CountrySidePanelProps {
  country: string | null
  onClose: () => void
}

export function CountrySidePanel({ country, onClose }: CountrySidePanelProps) {
  const { byCountry } = useLatestScores()
  const { events, isLoading } = useCountryEvents(country)
  const score = country ? byCountry.get(country) : undefined

  // Rendered inside the shared centred DetailOverlay (#207), which owns
  // positioning + animation — this is just the bounded, scrollable card.
  if (!country) return null

  return (
    <aside className="flex max-h-[82vh] w-[340px] max-w-[88vw] flex-col gap-4 overflow-y-auto rounded-md border border-neutral-800 bg-neutral-950/95 p-4 shadow-2xl backdrop-blur-md">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2.5">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`https://flagcdn.com/32x24/${country.toLowerCase()}.png`}
                alt=""
                width={32}
                height={24}
                className="rounded-sm border border-neutral-800"
              />
              <div className="flex flex-col">
                <span className="text-sm font-medium text-neutral-100">{countryName(country)}</span>
                <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                  {country}
                </span>
              </div>
            </div>
            <button
              type="button"
              aria-label="Close"
              onClick={onClose}
              className="text-neutral-500 hover:text-neutral-200"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Composite score */}
          <div className="flex items-end gap-3 rounded-lg border border-neutral-800 bg-neutral-900/50 p-3">
            <span
              className="font-mono text-4xl font-semibold leading-none"
              style={{ color: score ? scoreTextColor(score.score) : "#737373" }}
            >
              {score ? score.score.toFixed(2) : "—"}
            </span>
            <span className="pb-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
              composite
              <br />
              score
            </span>
          </div>

          {/* z-bars */}
          <div className="flex flex-col gap-2">
            <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
              Domain z-scores
            </span>
            {Z_DOMAINS.map((d) => (
              <ZBar key={d.key} label={d.label} value={score?.components?.z?.[d.key]} />
            ))}
          </div>

          {/* recent events */}
          <div className="flex min-h-0 flex-1 flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
              Recent events
            </span>
            <div className="-mx-2 flex-1 overflow-y-auto">
              {isLoading ? (
                <div className="flex flex-col gap-1.5 px-2 py-1">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="h-7 animate-pulse rounded-md bg-neutral-800/60" />
                  ))}
                </div>
              ) : events.length > 0 ? (
                events.map((ev) => <EventRowItem key={ev.id} ev={ev} />)
              ) : (
                <p className="px-2 py-4 text-xs text-neutral-600">No recent events.</p>
              )}
            </div>
          </div>
    </aside>
  )
}
