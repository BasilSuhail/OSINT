/**
 * CAMEO event-root code → human-readable label.
 *
 * GDELT v2 encodes each event with a 3-4 digit CAMEO code; the first one or two
 * digits identify the root behaviour (01..20). The composite worker only
 * consumes codes 14..20 (escalatory) — see `app/sources/gdelt_cameo.py` — but
 * the frontend should label cooperative codes too because they still show on
 * the map.
 */

export const CAMEO_ROOT_LABELS: Record<string, string> = {
  "01": "Public statement",
  "02": "Appeal",
  "03": "Intent to cooperate",
  "04": "Consult",
  "05": "Diplomatic cooperation",
  "06": "Material cooperation",
  "07": "Provide aid",
  "08": "Yield",
  "09": "Investigate",
  "10": "Demand",
  "11": "Disapprove",
  "12": "Reject",
  "13": "Threaten",
  "14": "Protest",
  "15": "Force posture",
  "16": "Reduce relations",
  "17": "Coerce",
  "18": "Assault",
  "19": "Fight",
  "20": "Mass violence",
}

/** Normalise a raw CAMEO code (e.g. `"14"`, `"143"`, `14`) to a 2-digit root. */
export function cameoRoot(code: string | number | undefined | null): string | null {
  if (code == null) return null
  const raw = String(code).trim()
  if (!raw) return null
  const root = raw.padStart(2, "0").slice(0, 2)
  return CAMEO_ROOT_LABELS[root] ? root : null
}

/** Return a human label for a CAMEO root code, or null if it's unrecognised. */
export function cameoLabel(code: string | number | undefined | null): string | null {
  const root = cameoRoot(code)
  return root ? CAMEO_ROOT_LABELS[root] : null
}
