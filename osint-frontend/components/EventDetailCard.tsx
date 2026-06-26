"use client"

import { useEffect, useMemo, useState } from "react"
import { format } from "date-fns"
import { ChevronDown, Copy, ExternalLink, X } from "lucide-react"
import { cameoLabel } from "@/lib/cameo"
import { colorForEvent, type EventRow } from "@/lib/types"
import { cn } from "@/lib/utils"
import { SourceSignals } from "./SourceSignals"

interface EventDetailCardProps {
  event: EventRow
  /** Optional ISO if known, opens CountrySidePanel. */
  onSelectCountry?: (iso: string) => void
  onClose: () => void
  /** Wrap in a fixed-position container? Set false when caller already positions (e.g. inside maplibre Popup). */
  embedded?: boolean
  className?: string
}

const HARD_LIMIT_PAYLOAD_KB = 32

function bestTitle(ev: EventRow): string {
  const p = ev.payload as Record<string, unknown>
  const source = (ev.source || "").toLowerCase()

  // GDELT: payload.event_root_code is the CAMEO root (e.g. "14"). Translate to
  // a human label and tack on the country_fips location free-text if present.
  if (source === "gdelt") {
    const cameo = cameoLabel(p?.event_root_code as string | number | undefined)
    const place = typeof p?.country_fips === "string" ? p.country_fips : null
    if (cameo && place) return `${cameo} · ${place}`
    if (cameo) return `${cameo} event`
  }

  // USGS: payload.place already reads "Off the east coast of Honshu, Japan".
  // Prefix the magnitude so the title is informative at a glance.
  if (source === "usgs-quake") {
    const mag = typeof p?.magnitude === "number" ? p.magnitude : null
    const place = typeof p?.place === "string" ? p.place : null
    if (mag && place) return `M${mag.toFixed(1)} · ${place}`
    if (place) return place
  }

  // GDACS: event_type + country_name. For earthquakes, prefix the magnitude
  // (same as USGS) so the headline reads "M6.9 · Venezuela" instead of a bare
  // "EARTHQUAKE · Venezuela" the user can scroll past.
  if (source === "gdacs") {
    const mag = typeof p?.magnitude === "number" ? p.magnitude : null
    const rawType = typeof p?.event_type === "string" ? p.event_type.toUpperCase() : null
    const type = rawType === "EQ" ? "EARTHQUAKE" : rawType
    const place = typeof p?.country_name === "string" ? p.country_name : null
    if (mag && place) return `M${mag.toFixed(1)} · ${place}`
    if (type && place) return `${type} · ${place}`
  }

  // yfinance: ticker + drawdown gives an at-a-glance reading.
  if (source === "yfinance" || source === "yf") {
    const tkr = typeof p?.ticker === "string" ? p.ticker : null
    const dd = typeof p?.drawdown_pct === "number" ? p.drawdown_pct : null
    if (tkr && dd != null) return `${tkr} drawdown ${dd.toFixed(1)}%`
    if (tkr) return tkr
  }

  // Generic fallback: try the usual title/headline/place fields.
  const candidates = [p?.title, p?.headline, p?.place, p?.country_name]
  for (const c of candidates) if (typeof c === "string" && c.trim()) return c
  return `${ev.source} event`
}

function bestSourceUrl(ev: EventRow): string | null {
  const p = ev.payload as Record<string, unknown>
  // GDELT's `source_url` field is the 15-min export file id (e.g.
  // "20260620064500"), not a real URL. Skip when it doesn't start with http.
  const direct = (p?.source_url ?? p?.link ?? p?.url) as string | undefined
  if (typeof direct === "string" && direct.startsWith("http")) return direct
  // USGS quakes store only `usgs_id` — no URL. Derive the canonical event page
  // so "open source" links straight to the ShakeMap / report like GDACS does.
  if (typeof p?.usgs_id === "string" && p.usgs_id) {
    return `https://earthquake.usgs.gov/earthquakes/eventpage/${p.usgs_id}`
  }
  const sources = p?.sources as Array<Record<string, unknown>> | undefined
  if (Array.isArray(sources) && sources[0]?.url && typeof sources[0].url === "string") {
    return sources[0].url as string
  }
  return null
}

function countryFlagEmoji(iso: string | null): string {
  if (!iso || iso.length !== 2) return ""
  const codePoints = iso
    .toUpperCase()
    .split("")
    .map((c) => 127397 + c.charCodeAt(0))
  return String.fromCodePoint(...codePoints)
}

function severityLabel(s: number): string {
  if (s >= 0.8) return "STRESS"
  if (s >= 0.6) return "WARNING"
  if (s >= 0.4) return "WATCH"
  return "CALM"
}

function severityBarColor(s: number): string {
  if (s >= 0.8) return "#ef4444"
  if (s >= 0.6) return "#f97316"
  if (s >= 0.4) return "#eab308"
  return "#22c55e"
}

function CopyButton({
  text,
  label,
  className,
}: {
  text: string
  label?: string
  className?: string
}) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setDone(true)
          window.setTimeout(() => setDone(false), 1200)
        } catch {
          /* clipboard unavailable */
        }
      }}
      title={label ?? "Copy"}
      className={cn(
        "inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500 hover:text-neutral-200",
        className,
      )}
    >
      <Copy className="h-3 w-3" />
      {done ? "copied" : label ?? "copy"}
    </button>
  )
}

/** GDACS-style 0–3 alert gauge. We store severity as 0–1; scale to 0–3 so the
 *  marker sits in green (<1) / orange (1–2) / red (>2) like the GDACS score bar. */
function ScoreGauge({ severity }: { severity: number }) {
  const score = Math.max(0, Math.min(3, severity * 3))
  const pct = (score / 3) * 100
  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
          Alert score
        </span>
        <span className="font-mono text-[11px] tabular-nums text-neutral-200">
          {score.toFixed(1)} / 3
        </span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full">
        <div className="absolute inset-0 flex">
          <div className="h-full flex-1" style={{ backgroundColor: "#22c55e" }} />
          <div className="h-full flex-1" style={{ backgroundColor: "#f97316" }} />
          <div className="h-full flex-1" style={{ backgroundColor: "#ef4444" }} />
        </div>
        <div
          className="absolute top-1/2 h-3 w-3 -translate-y-1/2 -translate-x-1/2 rounded-full border-2 border-white bg-neutral-900"
          style={{ left: `${pct}%` }}
          aria-hidden
        />
      </div>
    </div>
  )
}

export function EventDetailCard({
  event,
  onSelectCountry,
  onClose,
  embedded = false,
  className,
}: EventDetailCardProps) {
  const [payloadOpen, setPayloadOpen] = useState(false)
  const color = colorForEvent(event)
  const title = bestTitle(event)
  const url = bestSourceUrl(event)
  const flag = countryFlagEmoji(event.country)
  const sev = typeof event.severity === "number" ? event.severity : 0
  const p = (event.payload ?? {}) as Record<string, unknown>
  const isHazard = event.category === "hazard" || event.category === "weather"
  const payloadJson = useMemo(() => {
    const raw = JSON.stringify(event.payload ?? {}, null, 2)
    if (raw.length > HARD_LIMIT_PAYLOAD_KB * 1024) {
      return raw.slice(0, HARD_LIMIT_PAYLOAD_KB * 1024) + "\n… [truncated]"
    }
    return raw
  }, [event.payload])

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [onClose])

  return (
    <div
      className={cn(
        "w-80 max-w-[88vw] rounded-md border border-neutral-700 bg-neutral-950/95 p-3 text-neutral-200 backdrop-blur-md",
        embedded ? "" : "shadow-2xl",
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
          <span className="font-mono text-xs uppercase tracking-wider text-neutral-100">
            {event.source}
          </span>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="text-neutral-500 hover:text-neutral-200"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Title */}
      <p className="mt-2 line-clamp-3 text-[13px] font-medium text-neutral-100" title={title}>
        {title}
      </p>

      {/* Severity bar */}
      <div className="mt-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-800">
          <div
            className="h-full transition-all"
            style={{ width: `${Math.min(100, Math.max(2, sev * 100))}%`, backgroundColor: severityBarColor(sev) }}
          />
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
          {severityLabel(sev)} · {sev.toFixed(2)}
        </span>
      </div>

      {/* GDACS-style 0–3 score gauge + hazard metadata */}
      {isHazard && (
        <>
          <ScoreGauge severity={sev} />
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
            {(
              [
                ["Country", (p.country_name as string) || event.country],
                ["Magnitude", p.magnitude != null ? `M${Number(p.magnitude).toFixed(1)}` : null],
                ["Depth", p.depth_km != null ? `${Number(p.depth_km).toFixed(0)} km` : null],
                ["Burned area", typeof p.severity_raw === "string" ? p.severity_raw : null],
                ["ID", (p.gdacs_event_id as string) || (p.usgs_id as string) || null],
              ] as [string, string | null][]
            )
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-neutral-500">{k}</dt>
                  <dd className="truncate text-neutral-200">{v as string}</dd>
                </div>
              ))}
          </dl>
        </>
      )}

      {/* Field grid */}
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
        <dt className="text-neutral-500">category</dt>
        <dd className="text-neutral-300">{event.category}</dd>

        <dt className="text-neutral-500">occurred</dt>
        <dd className="text-neutral-300">
          {format(new Date(event.occurred_at), "yyyy-MM-dd HH:mm 'UTC'")}
        </dd>

        {event.country && (
          <>
            <dt className="text-neutral-500">country</dt>
            <dd className="text-neutral-300">
              {flag} {event.country}
            </dd>
          </>
        )}

        {event.lat != null && event.lon != null && (
          <>
            <dt className="text-neutral-500">lat / lon</dt>
            <dd className="flex items-center gap-2 text-neutral-300">
              <span>
                {event.lat.toFixed(3)}, {event.lon.toFixed(3)}
              </span>
              <CopyButton text={`${event.lat},${event.lon}`} label="latlon" />
            </dd>
          </>
        )}

        <dt className="text-neutral-500">event id</dt>
        <dd className="flex items-center gap-2 text-neutral-300">
          <span className="truncate" title={event.source_event_id ?? ""}>
            {event.source_event_id ?? "—"}
          </span>
          {event.source_event_id && <CopyButton text={event.source_event_id} label="id" />}
        </dd>
      </dl>

      {/* Per-source signals */}
      <SourceSignals ev={event} />

      {/* Keywords */}
      {event.keywords && event.keywords.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {event.keywords.slice(0, 12).map((k) => (
            <span
              key={k}
              className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px] text-neutral-300"
            >
              {k}
            </span>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-neutral-800 pt-2">
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-cyan-400 hover:text-cyan-300"
          >
            open source <ExternalLink className="h-2.5 w-2.5" />
          </a>
        )}
        {event.country && onSelectCountry && (
          <button
            type="button"
            onClick={() => onSelectCountry(event.country as string)}
            className="font-mono text-[10px] uppercase tracking-widest text-emerald-400 hover:text-emerald-300"
          >
            country detail
          </button>
        )}
        <CopyButton text={JSON.stringify(event, null, 2)} label="copy json" />
      </div>

      {/* Raw payload */}
      <button
        type="button"
        onClick={() => setPayloadOpen((o) => !o)}
        className="mt-3 flex w-full items-center justify-between rounded bg-neutral-900 px-2 py-1 font-mono text-[10px] uppercase tracking-widest text-neutral-400 hover:text-neutral-200"
      >
        <span>raw payload</span>
        <ChevronDown
          className={cn(
            "h-3 w-3 transition-transform",
            payloadOpen ? "rotate-180" : "",
          )}
        />
      </button>
      {payloadOpen && (
        <pre className="mt-1 max-h-60 overflow-auto rounded bg-neutral-900 p-2 font-mono text-[10px] leading-tight text-neutral-300">
          {payloadJson}
        </pre>
      )}
    </div>
  )
}
