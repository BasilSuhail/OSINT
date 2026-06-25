"use client"

import type { EventRow } from "@/lib/types"

interface RowProps {
  label: string
  value: string | number | null | undefined
  /** Optional tooltip explaining the field for non-experts. */
  hint?: string
}

function Row({ label, value, hint }: RowProps) {
  if (value === null || value === undefined || value === "") return null
  return (
    <>
      <dt className="text-neutral-500" title={hint}>
        {label}
      </dt>
      <dd className="text-neutral-300">{value}</dd>
    </>
  )
}

function asNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v
  if (typeof v === "string" && v.trim()) {
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function asString(v: unknown): string | null {
  if (typeof v === "string" && v.trim()) return v
  return null
}

/**
 * Per-source signal block rendered inside EventDetailCard. Picks out the
 * fields a viewer actually cares about for each source so they don't have
 * to expand the raw JSON every time.
 */
export function SourceSignals({ ev }: { ev: EventRow }) {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const source = (ev.source || "").toLowerCase()

  let rows: { label: string; value: string | number | null | undefined; hint?: string }[]

  if (source === "gdelt") {
    const tone = asNumber(p.avg_tone)
    const goldstein = asNumber(p.goldstein)
    const mentions = asNumber(p.num_mentions)
    rows = [
      {
        label: "tone",
        value: tone !== null ? tone.toFixed(2) : null,
        hint: "GDELT avg_tone: < 0 negative, > 0 positive",
      },
      {
        label: "goldstein",
        value: goldstein !== null ? goldstein.toFixed(1) : null,
        hint: "Goldstein scale: -10 worst to +10 best",
      },
      {
        label: "mentions",
        value: mentions !== null ? mentions : null,
        hint: "Distinct articles mentioning this event",
      },
      { label: "cameo", value: asString(p.event_root_code) },
    ]
  } else if (source === "usgs-quake") {
    const mag = asNumber(p.magnitude)
    const depth = asNumber(p.depth_km)
    rows = [
      { label: "magnitude", value: mag !== null ? `M${mag.toFixed(1)}` : null },
      { label: "depth", value: depth !== null ? `${depth.toFixed(1)} km` : null },
      { label: "PAGER", value: asString(p.alert) ?? "—" },
      { label: "tsunami", value: asNumber(p.tsunami) ? "yes" : null },
      { label: "felt", value: asNumber(p.felt) },
    ]
  } else if (source === "gdacs") {
    // Earthquakes carry magnitude (value attr) + depth (parsed from text);
    // other hazards leave both null so the rows drop out. severity_raw is the
    // free-text blurb ("Magnitude 6.9M, Depth:50.9km") and is no longer numeric.
    const mag = asNumber(p.magnitude)
    const depth = asNumber(p.depth_km)
    rows = [
      { label: "type", value: asString(p.event_type)?.toUpperCase() ?? null },
      { label: "alert", value: asString(p.alert_level)?.toUpperCase() ?? null },
      { label: "magnitude", value: mag !== null ? `M${mag.toFixed(1)}` : null },
      { label: "depth", value: depth !== null ? `${depth.toFixed(1)} km` : null },
    ]
  } else if (source === "yfinance" || source === "yf") {
    const close = asNumber(p.close)
    const dd = asNumber(p.drawdown_pct)
    rows = [
      { label: "ticker", value: asString(p.ticker) },
      { label: "close", value: close !== null ? close.toFixed(2) : null },
      {
        label: "drawdown",
        value: dd !== null ? `${dd.toFixed(2)}%` : null,
        hint: "Pct fall from 30-day rolling max",
      },
    ]
  } else if (source === "fred") {
    rows = [
      { label: "series", value: asString(p.series_id) ?? asString(p.id) },
      { label: "value", value: asNumber(p.value)?.toString() ?? null },
      { label: "units", value: asString(p.units) },
    ]
  } else if (source === "eonet") {
    const cats = Array.isArray(p.categories) ? (p.categories as string[]).join(", ") : null
    const mv = asNumber(p.magnitude_value)
    const mu = asString(p.magnitude_unit)
    rows = [
      { label: "category", value: cats },
      {
        label: "magnitude",
        value: mv !== null && mu ? `${mv.toFixed(1)} ${mu}` : mv?.toString() ?? null,
      },
      { label: "geometry", value: asString(p.geometry_type) },
      { label: "closed", value: asString(p.closed) ?? null },
    ]
  } else if (source === "nasa-firms") {
    const brightness = asNumber(p.brightness)
    const frp = asNumber(p.frp)
    rows = [
      {
        label: "brightness",
        value: brightness !== null ? `${brightness.toFixed(1)} K` : null,
        hint: "VIIRS channel-I4 brightness temperature",
      },
      {
        label: "FRP",
        value: frp !== null ? `${frp.toFixed(1)} MW` : null,
        hint: "Fire Radiative Power",
      },
      { label: "satellite", value: asString(p.satellite) },
      { label: "confidence", value: asString(p.confidence_raw) },
      { label: "day/night", value: asString(p.daynight) },
    ]
  } else {
    return null
  }

  const visible = rows.filter((r) => r.value !== null && r.value !== undefined && r.value !== "")
  if (visible.length === 0) return null

  return (
    <div className="mt-3 border-t border-neutral-800 pt-2">
      <p className="mb-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
        Source signal
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
        {visible.map((r) => (
          <Row key={r.label} label={r.label} value={r.value} hint={r.hint} />
        ))}
      </dl>
    </div>
  )
}
