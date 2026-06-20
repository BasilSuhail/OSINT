"use client"

import { useEffect, useMemo, useState } from "react"
import { format } from "date-fns"
import { ChevronDown, Copy, ExternalLink, X } from "lucide-react"
import { colorForEvent, type EventRow } from "@/lib/types"
import { cn } from "@/lib/utils"

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
  const candidates = [p?.title, p?.place, p?.country_name, p?.event_root_code, p?.headline]
  for (const c of candidates) if (typeof c === "string" && c.trim()) return c
  return `${ev.source} event`
}

function bestSourceUrl(ev: EventRow): string | null {
  const p = ev.payload as Record<string, unknown>
  const direct = (p?.source_url ?? p?.link ?? p?.url) as string | undefined
  if (typeof direct === "string" && direct.startsWith("http")) return direct
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
