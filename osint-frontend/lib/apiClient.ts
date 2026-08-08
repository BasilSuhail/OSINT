import type { EventRow, IngestHealthRow, ScoreRow, SourceCoverageRow } from "./types"

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

/** Shared secret the API requires when one is configured (#824). Empty in a
 *  development stack, where the API is open and says so at startup. */
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? ""

/** Every request to the API goes through here.
 *
 * A header the caller has to remember is a header somebody will forget on the
 * next endpoint, and the failure mode is a panel that silently 401s. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  if (!API_TOKEN) return fetch(input, init)
  const headers = new Headers(init.headers)
  headers.set("X-API-Key", API_TOKEN)
  return fetch(input, { ...init, headers })
}



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
  scoreRows: intEnv(process.env.NEXT_PUBLIC_SCORE_ROW_LIMIT, 2000, 500, 10000),
  analyticsRows: intEnv(process.env.NEXT_PUBLIC_ANALYTICS_ROW_LIMIT, 7500, 1000, 10000),
}

// Local API always has a valid default base; kept as a named export so call
// sites read the same way the old isSupabaseConfigured did.
export const isApiConfigured = true

export interface EventQuery {
  since?: string
  until?: string
  fetchedSince?: string
  updatedSince?: string
  updatedAfterId?: string
  occurredBefore?: string
  occurredBeforeId?: string
  west?: number
  south?: number
  east?: number
  north?: number
  positionedOnly?: boolean
  country?: string
  sources?: string[]
  exclude?: string[]
  limit?: number
}

export async function fetchEvents(
  params: EventQuery = {},
  options: { signal?: AbortSignal } = {},
): Promise<EventRow[]> {
  const qs = new URLSearchParams()
  if (params.since) qs.set("since", params.since)
  if (params.until) qs.set("until", params.until)
  if (params.fetchedSince) qs.set("fetched_since", params.fetchedSince)
  if (params.updatedSince) qs.set("updated_since", params.updatedSince)
  if (params.updatedAfterId) qs.set("updated_after_id", params.updatedAfterId)
  if (params.occurredBefore) qs.set("occurred_before", params.occurredBefore)
  if (params.occurredBeforeId) qs.set("occurred_before_id", params.occurredBeforeId)
  if (params.west != null) qs.set("west", String(params.west))
  if (params.south != null) qs.set("south", String(params.south))
  if (params.east != null) qs.set("east", String(params.east))
  if (params.north != null) qs.set("north", String(params.north))
  if (params.positionedOnly != null) qs.set("positioned_only", String(params.positionedOnly))
  if (params.country) qs.set("country", params.country)
  if (params.sources?.length) qs.set("sources", params.sources.join(","))
  if (params.exclude?.length) qs.set("exclude", params.exclude.join(","))
  if (params.limit != null) qs.set("limit", String(params.limit))
  const q = qs.toString()
  const res = await apiFetch(`${API_BASE}/events${q ? `?${q}` : ""}`, {
    signal: options.signal,
  })
  if (!res.ok) throw new Error(`GET /events ${res.status}`)
  return (await res.json()) as EventRow[]
}

/** Fetch every event in a bounded query without letting the API's page limit
 * silently choose which streets or buildings exist on the map. */
export async function fetchAllEventPages(
  params: Omit<EventQuery, "limit" | "occurredBefore" | "occurredBeforeId">,
  pageSize = 2000,
  options: { signal?: AbortSignal } = {},
): Promise<EventRow[]> {
  const rows: EventRow[] = []
  const seenCursors = new Set<string>()
  let cursor: Pick<EventQuery, "occurredBefore" | "occurredBeforeId"> = {}

  for (;;) {
    const page = await fetchEvents({ ...params, ...cursor, limit: pageSize }, options)
    rows.push(...page)
    if (page.length < pageSize) return rows

    const last = page.at(-1)
    if (!last) return rows
    const nextCursor = `${last.occurred_at}|${last.id}`
    if (seenCursors.has(nextCursor)) {
      throw new Error("GET /events occurrence cursor did not advance")
    }
    seenCursors.add(nextCursor)
    cursor = { occurredBefore: last.occurred_at, occurredBeforeId: String(last.id) }
  }
}

/** Page every row revised after a durable cursor. This complements occurrence
 * paging so late-ingested or backfilled rows remain discoverable. */
export async function fetchAllUpdatedEventPages(
  params: Omit<
    EventQuery,
    "limit" | "updatedSince" | "updatedAfterId" | "occurredBefore" | "occurredBeforeId"
  >,
  updatedSince: string,
  pageSize = 2000,
  options: { signal?: AbortSignal } = {},
): Promise<EventRow[]> {
  const rows: EventRow[] = []
  const seenCursors = new Set<string>()
  let cursor: Pick<EventQuery, "updatedSince" | "updatedAfterId"> = { updatedSince }

  for (;;) {
    const page = await fetchEvents({ ...params, ...cursor, limit: pageSize }, options)
    rows.push(...page)
    if (page.length < pageSize) return rows

    const last = page.at(-1)
    if (!last?.updated_at) throw new Error("GET /events revision cursor is missing")
    const nextCursor = `${last.updated_at}|${last.id}`
    if (seenCursors.has(nextCursor)) {
      throw new Error("GET /events revision cursor did not advance")
    }
    seenCursors.add(nextCursor)
    cursor = { updatedSince: last.updated_at, updatedAfterId: String(last.id) }
  }
}

/** Headline world stats, aggregated in Postgres (#499).
 *
 *  These used to be derived from the client's event buffer, which meant the
 *  header reported the buffer cap (7500) rather than the data. The server
 *  counts instead, so the figures stay true at constant browser memory. */
export interface EventStats {
  total: number
  countries: number
  sources: number
  top_countries: { country: string; count: number }[]
  spark: number[]
}

export async function fetchEventStats(days = 30): Promise<EventStats> {
  const res = await apiFetch(`${API_BASE}/events/stats?days=${days}`)
  if (!res.ok) throw new Error(`GET /events/stats ${res.status}`)
  return (await res.json()) as EventStats
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
  const res = await apiFetch(`${API_BASE}/scores${q ? `?${q}` : ""}`)
  if (!res.ok) throw new Error(`GET /scores ${res.status}`)
  return (await res.json()) as ScoreRow[]
}

export async function fetchIngestHealth(days = 7): Promise<IngestHealthRow[]> {
  const res = await apiFetch(`${API_BASE}/ingest-health?days=${days}`)
  if (!res.ok) throw new Error(`GET /ingest-health ${res.status}`)
  return (await res.json()) as IngestHealthRow[]
}

export async function fetchSourceCoverage(days = 30): Promise<SourceCoverageRow[]> {
  const res = await apiFetch(`${API_BASE}/events/coverage?days=${days}`)
  if (!res.ok) throw new Error(`GET /events/coverage ${res.status}`)
  return (await res.json()) as SourceCoverageRow[]
}

export function streamUrl(): string {
  const url = `${API_BASE}/stream`
  // EventSource cannot send headers, so the stream carries its credential in
  // the query string (#824). Stated rather than hidden: a token in a URL can
  // reach a proxy log, which is why the API accepts one this way on this
  // read-only endpoint and nowhere else.
  return API_TOKEN ? `${url}?token=${encodeURIComponent(API_TOKEN)}` : url
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
  const res = await apiFetch(`${API_BASE}/brain/narrative/latest`)
  if (!res.ok) throw new Error(`brain narrative ${res.status}`)
  return (await res.json()) as BrainNarrative
}

export interface BrainSource {
  n: number
  /** null for sensor readings (#507): an instrument record has no story to
   *  open, so a (source) chip backed by one is a label, not a link. */
  story_id: number | null
  title: string
  outlets: string[]
  corroboration: number | null
  contested: boolean
}

/** One answer sentence mapped to the stories that back it (#476). */
export interface AskClaim {
  text: string
  cited: number[]
  supported: boolean
  matched_story: number | null
}

/** Compact retrieval reasoning shown in the (thinking) popup (#476). */
export interface AskReasoning {
  method: string | null
  intents: string[]
  terms: string[]
}

export interface BrainAsk {
  answer: string
  context_digest: string | null
  sources: BrainSource[]
  /** Weak-retrieval fallback (#459): retrieved stories shown separately, never as evidence. */
  closest_matches?: BrainSource[]
  claims?: AskClaim[]
  reasoning?: AskReasoning | null
}

/** One prior transcript turn sent with an ask (#444) — anchors follow-ups. */
export interface AskExchange {
  question: string
  answer: string
  /** Stories cited in this turn (#813). "What else?" can only be answered with
   *  something else if the server knows what was already shown. */
  story_ids: number[]
}

export async function fetchBrainAsk(
  question: string,
  history: AskExchange[] = [],
): Promise<BrainAsk> {
  const res = await apiFetch(`${API_BASE}/brain/ask`, {
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
  const res = await apiFetch(`${API_BASE}/brain/ask/stream`, {
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

export interface SearchPlace {
  name: string
  lat: number
  lon: number
  country: string | null
  kind: "city" | "region" | "country"
  context: string
  population: number
}

export interface SearchResponse {
  query: string
  ambiguous: boolean
  places: SearchPlace[]
  events: EventRow[]
}

/** One query over places and content (#779).
 *
 *  Takes a signal because the caller types faster than the server answers:
 *  without cancellation an early slow response lands after a later fast one
 *  and the reader watches results for a query they have already replaced. */
export async function fetchSearch(
  q: string,
  options: { signal?: AbortSignal; limit?: number } = {},
): Promise<SearchResponse> {
  const qs = new URLSearchParams({ q })
  if (options.limit) qs.set("limit", String(options.limit))
  const res = await apiFetch(`${API_BASE}/search?${qs.toString()}`, { signal: options.signal })
  if (!res.ok) throw new Error(`search failed: ${res.status}`)
  return (await res.json()) as SearchResponse
}
