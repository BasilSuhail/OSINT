import type { EventRow, IngestHealthRow, ScoreRow, SourceCoverageRow } from "./types"

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

// Local API always has a valid default base; kept as a named export so call
// sites read the same way the old isSupabaseConfigured did.
export const isApiConfigured = true

export interface EventQuery {
  since?: string
  fetchedSince?: string
  country?: string
  sources?: string[]
  exclude?: string[]
  limit?: number
}

export async function fetchEvents(params: EventQuery = {}): Promise<EventRow[]> {
  const qs = new URLSearchParams()
  if (params.since) qs.set("since", params.since)
  if (params.fetchedSince) qs.set("fetched_since", params.fetchedSince)
  if (params.country) qs.set("country", params.country)
  if (params.sources?.length) qs.set("sources", params.sources.join(","))
  if (params.exclude?.length) qs.set("exclude", params.exclude.join(","))
  if (params.limit != null) qs.set("limit", String(params.limit))
  const q = qs.toString()
  const res = await fetch(`${API_BASE}/events${q ? `?${q}` : ""}`)
  if (!res.ok) throw new Error(`GET /events ${res.status}`)
  return (await res.json()) as EventRow[]
}

export interface ScoreQuery {
  scoreName?: string
  since?: string
  country?: string
  limit?: number
}

export async function fetchScores(params: number | ScoreQuery = 5000): Promise<ScoreRow[]> {
  const query = typeof params === "number" ? { limit: params } : params
  const qs = new URLSearchParams()
  if (query.scoreName) qs.set("score_name", query.scoreName)
  if (query.since) qs.set("since", query.since)
  if (query.country) qs.set("country", query.country)
  if (query.limit != null) qs.set("limit", String(query.limit))
  const q = qs.toString()
  const res = await fetch(`${API_BASE}/scores${q ? `?${q}` : ""}`)
  if (!res.ok) throw new Error(`GET /scores ${res.status}`)
  return (await res.json()) as ScoreRow[]
}

export async function fetchIngestHealth(days = 7): Promise<IngestHealthRow[]> {
  const res = await fetch(`${API_BASE}/ingest-health?days=${days}`)
  if (!res.ok) throw new Error(`GET /ingest-health ${res.status}`)
  return (await res.json()) as IngestHealthRow[]
}

export async function fetchSourceCoverage(days = 30): Promise<SourceCoverageRow[]> {
  const res = await fetch(`${API_BASE}/events/coverage?days=${days}`)
  if (!res.ok) throw new Error(`GET /events/coverage ${res.status}`)
  return (await res.json()) as SourceCoverageRow[]
}

export function streamUrl(): string {
  return `${API_BASE}/stream`
}
