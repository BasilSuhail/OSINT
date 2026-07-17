import type { EventRow, IngestHealthRow, ScoreRow, SourceCoverageRow } from "./types"

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

function intEnv(raw: string | undefined, fallback: number, min: number, max: number): number {
  if (!raw) return fallback
  const parsed = Number.parseInt(raw, 10)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, parsed))
}

export const CLIENT_LIMITS = {
  eventWindow: intEnv(process.env.NEXT_PUBLIC_EVENT_WINDOW_LIMIT, 5000, 500, 10000),
  eventBuffer: intEnv(process.env.NEXT_PUBLIC_EVENT_BUFFER_LIMIT, 7500, 1000, 15000),
  hazardEvents: intEnv(process.env.NEXT_PUBLIC_HAZARD_EVENT_LIMIT, 2500, 250, 10000),
  cyberEvents: intEnv(process.env.NEXT_PUBLIC_CYBER_EVENT_LIMIT, 1000, 250, 5000),
  firmsEvents: intEnv(process.env.NEXT_PUBLIC_FIRMS_EVENT_LIMIT, 1000, 250, 5000),
  scoreRows: intEnv(process.env.NEXT_PUBLIC_SCORE_ROW_LIMIT, 2000, 500, 10000),
  analyticsRows: intEnv(process.env.NEXT_PUBLIC_ANALYTICS_ROW_LIMIT, 7500, 1000, 10000),
}

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

export async function fetchScores(params: number | ScoreQuery = CLIENT_LIMITS.scoreRows): Promise<ScoreRow[]> {
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

export interface BrainNarrative {
  present: boolean
  payload: {
    headline?: string
    world?: string
    system?: string
    watch?: string[]
  } | null
  model: string | null
  created_at: string | null
}

export async function fetchBrainNarrative(): Promise<BrainNarrative> {
  const res = await fetch(`${API_BASE}/brain/narrative/latest`)
  if (!res.ok) throw new Error(`brain narrative ${res.status}`)
  return (await res.json()) as BrainNarrative
}

export interface BrainSource {
  n: number
  story_id: number
  title: string
  outlets: string[]
  corroboration: number | null
  contested: boolean
}

export interface BrainAsk {
  answer: string
  context_digest: string | null
  sources: BrainSource[]
}

/** One prior transcript turn sent with an ask (#444) — anchors follow-ups. */
export interface AskExchange {
  question: string
  answer: string
}

export async function fetchBrainAsk(
  question: string,
  history: AskExchange[] = [],
): Promise<BrainAsk> {
  const res = await fetch(`${API_BASE}/brain/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  })
  if (!res.ok) throw new Error(`brain ask ${res.status}`)
  return (await res.json()) as BrainAsk
}

type BrainAskStreamHandlers = {
  onDelta?: (text: string) => void
  onSources?: (sources: BrainSource[], contextDigest: string | null) => void
}

function parseSseBlock(block: string): { event: string; data: unknown } | null {
  let event = "message"
  const dataLines: string[] = []
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice("event:".length).trim()
    if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trimStart())
  }
  if (!dataLines.length) return null
  return { event, data: JSON.parse(dataLines.join("\n")) }
}

export async function streamBrainAsk(
  question: string,
  handlers: BrainAskStreamHandlers = {},
  history: AskExchange[] = [],
): Promise<BrainAsk> {
  const res = await fetch(`${API_BASE}/brain/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  })
  if (!res.ok) throw new Error(`brain ask stream ${res.status}`)
  if (!res.body) return fetchBrainAsk(question, history)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let latest: BrainAsk | null = null

  const handle = (block: string) => {
    const msg = parseSseBlock(block)
    if (!msg) return
    if (msg.event === "sources") {
      const data = msg.data as { sources: BrainSource[]; context_digest: string | null }
      handlers.onSources?.(data.sources, data.context_digest)
      return
    }
    if (msg.event === "delta") {
      const data = msg.data as { text: string }
      handlers.onDelta?.(data.text)
      return
    }
    if (msg.event === "final") latest = msg.data as BrainAsk
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (value) {
      buffer += decoder.decode(value, { stream: !done })
      const blocks = buffer.split("\n\n")
      buffer = blocks.pop() || ""
      for (const block of blocks) handle(block)
    }
    if (done) break
  }
  if (buffer.trim()) handle(buffer)
  if (!latest) throw new Error("brain ask stream ended without final")
  return latest
}
