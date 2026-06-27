import type { EventRow } from "./types"

const GDACS_GRACE_MS = 48 * 60 * 60 * 1000

function payload(ev: EventRow): Record<string, unknown> {
  return (ev.payload ?? {}) as Record<string, unknown>
}

function boolValue(raw: unknown): boolean | null {
  if (typeof raw === "boolean") return raw
  if (typeof raw === "string") {
    const text = raw.trim().toLowerCase()
    if (text === "true") return true
    if (text === "false") return false
  }
  return null
}

function timeMs(raw: unknown): number | null {
  if (typeof raw !== "string" || !raw.trim()) return null
  const ms = new Date(raw).getTime()
  return Number.isFinite(ms) ? ms : null
}

export function isPersistentActiveHazard(ev: EventRow, nowMs = Date.now()): boolean {
  if (ev.category !== "hazard") return false

  const src = (ev.source ?? "").toLowerCase()
  const p = payload(ev)

  if (src.includes("gdacs")) {
    const current = boolValue(p.is_current)
    if (current === true) return true
    if (current === false) return false

    // Backward compatibility for rows ingested before `is_current` was stored.
    const toMs = timeMs(p.to_date)
    return toMs !== null && toMs + GDACS_GRACE_MS >= nowMs
  }

  if (src.includes("eonet")) {
    return p.closed == null
  }

  return false
}
