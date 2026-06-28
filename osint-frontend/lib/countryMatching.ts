import type { EventRow } from "./types"

type Payload = Record<string, unknown>

function payload(ev: EventRow): Payload {
  return (ev.payload ?? {}) as Payload
}

function affectedCountryCodes(ev: EventRow): string[] {
  const raw = payload(ev).affected_countries
  if (!Array.isArray(raw)) return []

  const codes: string[] = []
  for (const item of raw) {
    if (!item || typeof item !== "object") continue
    const iso2 = (item as Record<string, unknown>).iso2
    if (typeof iso2 === "string" && iso2.trim()) {
      codes.push(iso2.trim().toUpperCase())
    }
  }
  return codes
}

export function countryCodesForEvent(ev: EventRow): string[] {
  const codes = new Set<string>()
  if (ev.country) codes.add(ev.country)
  for (const code of affectedCountryCodes(ev)) codes.add(code)
  return [...codes]
}

export function eventMatchesCountry(ev: EventRow, countries: Set<string>): boolean {
  if (countries.size === 0) return true

  for (const code of countryCodesForEvent(ev)) {
    if (countries.has(code)) return true
  }

  return false
}
