import type { PlaceTarget } from "@/stores/placeStore"
import { placeUrl } from "./placeUrl"
import type { PresenceAnswer } from "./presence"
import type { VesselAnswer } from "./vessels"
import type { EventRow, IngestHealthRow, ScoreRow, SourceCoverageRow } from "./types"

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

/** Shared secret the API requires when one is configured (#824). Empty in a
 *  development stack, where the API is open and says so at startup. */
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? ""

/** How long any single API call may take before it is treated as a failure.
 *
 * A dead API is indistinguishable from a slow one to a client that waits
 * forever (#839). When the uvicorn worker was OOM-killed, the container kept
 * the socket bound with nothing behind it: connections were accepted and never
 * answered, so every panel sat on "loading…" indefinitely and the console had
 * no way to say the API was not answering.
 *
 * Generous rather than tight — a wide viewport page legitimately takes a few
 * seconds — but bounded, because an unbounded wait is not patience, it is a
 * missing error state. */
export const API_TIMEOUT_MS = 15_000

/** How long a single ask may take before it is treated as a failure.
 *
 * Inference is not a page load and cannot share its budget. Measured against
 * the live stack, one non-streamed ask took 24.2s end to end — a 4B model on
 * CPU, working correctly. Under the page budget it was cut off at 15s every
 * time, which the console then reported as the brain being offline. */
export const ASK_TIMEOUT_MS = 180_000

/** How long a stream may go quiet before it is treated as dead.
 *
 * A streamed answer cannot be judged on total elapsed time: retrieval lands in
 * about a second and the first token follows only once the model has read the
 * context — 17.8s on the measured run, with the answer still arriving normally
 * afterwards. What distinguishes a working generation from a dead one is not
 * how long it takes but whether anything is still coming, so the clock restarts
 * on every chunk. */
export const STREAM_IDLE_TIMEOUT_MS = 45_000

/** Combine the caller's cancellation with the timeout, so a viewport change
 *  still aborts in-flight work and a hung API still gives up.
 *
 *  `timeoutMs: null` means the caller owns the deadline — used by the streaming
 *  ask, which replaces the total budget with an idle one. */
function withTimeout(
  signal: AbortSignal | null | undefined,
  timeoutMs: number | null,
): AbortSignal | undefined {
  if (timeoutMs === null) return signal ?? undefined
  const timeout = AbortSignal.timeout(timeoutMs)
  if (!signal) return timeout
  // `AbortSignal.any` is the standard composition; fall back to the caller's
  // own signal where it is unavailable rather than dropping their cancellation.
  return typeof AbortSignal.any === "function" ? AbortSignal.any([signal, timeout]) : signal
}

/** A deadline that only runs while nothing is happening.
 *
 * `AbortSignal.timeout` fires a fixed interval after it is created, which is
 * the right shape for a request that either answers or does not. A stream is
 * a series of answers, so its guard has to be restarted by each one. */
function idleDeadline(idleMs: number): {
  signal: AbortSignal
  sawActivity: () => void
  done: () => void
} {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout>
  const arm = () => {
    timer = setTimeout(
      () => controller.abort(new DOMException("idle timeout", "TimeoutError")),
      idleMs,
    )
  }
  arm()
  return {
    signal: controller.signal,
    sawActivity: () => {
      clearTimeout(timer)
      arm()
    },
    done: () => clearTimeout(timer),
  }
}

/** Every request to the API goes through here.
 *
 * A header the caller has to remember is a header somebody will forget on the
 * next endpoint, and the failure mode is a panel that silently 401s. The same
 * argument applies to the timeout: a call that can hang is a spinner that can
 * never resolve, and no panel should have to remember to guard against it. */
export async function apiFetch(
  input: string,
  init: RequestInit = {},
  { timeoutMs = API_TIMEOUT_MS }: { timeoutMs?: number | null } = {},
): Promise<Response> {
  const signal = withTimeout(init.signal, timeoutMs)
  if (!API_TOKEN) return fetch(input, { ...init, signal })
  const headers = new Headers(init.headers)
  headers.set("X-API-Key", API_TOKEN)
  return fetch(input, { ...init, headers, signal })
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
  const res = await apiFetch(
    `${API_BASE}/brain/ask`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    },
    { timeoutMs: ASK_TIMEOUT_MS },
  )
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
  { idleMs = STREAM_IDLE_TIMEOUT_MS }: { idleMs?: number } = {},
): Promise<BrainAsk> {
  //: The stream governs itself: a total budget cannot tell a model that is
  //: still thinking from one that has died, and cutting off the former is
  //: what made a working brain report itself offline.
  const idle = idleDeadline(idleMs)
  const res = await apiFetch(
    `${API_BASE}/brain/ask/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
      signal: idle.signal,
    },
    { timeoutMs: null },
  )
  if (!res.ok) {
    idle.done()
    throw new Error(`brain ask stream ${res.status}`)
  }
  if (!res.body) {
    idle.done()
    return fetchBrainAsk(question, history)
  }

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

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (value) {
        //: Every chunk is proof the generation is alive, so it restarts the
        //: clock. Silence, not slowness, is what ends an ask.
        idle.sawActivity()
        buffer += decoder.decode(value, { stream: !done })
        const blocks = buffer.split("\n\n")
        buffer = blocks.pop() || ""
        for (const block of blocks) handle(block)
      }
      if (done) break
    }
  } finally {
    idle.done()
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

/** What the server knows about a place (#862).
 *
 *  Every block is nullable and every null one is named in `degraded`. Three
 *  third-party services answer this and none of them is ours, so a missing
 *  block is an ordinary Tuesday rather than an error — the screen says which
 *  went quiet instead of pretending the place has no capital.
 */
export interface PlaceCountry {
  iso2: string
  name: string
  border_distance_km: number | null
  near_border: boolean
}

export interface PlaceProfile {
  capital: string | null
  population: number | null
  area_km2: number | null
  languages: string[]
  currencies: string[]
}

export interface PlaceGovernment {
  type: string | null
  head_of_state: string | null
  head_of_government: string | null
  as_of: string
}

export interface PlaceSummary {
  title: string | null
  extract: string | null
  url: string | null
  thumbnail: string | null
}

export interface PlaceImagery {
  url: string
  full_url: string
  captured_at: string | null
  cloud_cover_pct: number | null
  item_id: string
}

export interface PlaceNextPass {
  at: string
  platform: string
  hours_away: number
}

/** The settlement standing at the point, and how far it is from it (#932).
 *
 *  Null is an answer, not a gap: past 100 km there is nothing near enough to
 *  call context, and the panel says so rather than naming a city in the next
 *  country. `population` may be null for a place Wikidata has no figure for —
 *  a village is still a village.
 */
export interface PlaceCity {
  name: string
  region: string | null
  distance_km: number
  population: number | null
}

/** Conditions over the coordinate, not over the town (#932).
 *
 *  `range_hours` is what the high and low actually cover. It is normally 24 and
 *  is smaller at the end of a forecast, and printing it is what keeps the
 *  numbers honest.
 */
export interface PlaceWeather {
  temperature_c: number | null
  wind_ms: number | null
  wind_from_deg: number | null
  humidity_pct: number | null
  conditions: string | null
  high_c: number | null
  low_c: number | null
  range_hours: number
  observed_at: string | null
}

export interface PlaceAnswer {
  point: { lat: number; lon: number } | null
  city: PlaceCity | null
  weather: PlaceWeather | null
  country: PlaceCountry | null
  profile: PlaceProfile | null
  government: PlaceGovernment | null
  summary: PlaceSummary | null
  imagery: PlaceImagery | null
  next_pass: PlaceNextPass | null
  degraded: string[]
}

/** One line of the calendar (#934).
 *
 *  A day in a country, not an item: `count` above one means several contests
 *  were collapsed, and `headline` then names the number rather than picking one
 *  of them. `kind` is only set for a single scheduled thing, because a mixed
 *  day has no single kind to report.
 */
export interface UpcomingEntry {
  starts_on: string
  iso: string | null
  country: string | null
  headline: string
  kind: string | null
  count: number
}

export interface UpcomingAnswer {
  fetched_at: string
  days: number
  count: number
  entries: UpcomingEntry[]
  degraded: boolean
}

/** Elections, referendums and summits still to come.
 *
 *  Its own request rather than part of the place answer: the upstream is slower
 *  than the place screen's per-source budget, and a cold calendar must not take
 *  the country facts down with it.
 */
export async function fetchUpcoming(
  iso: string | null,
  options: { signal?: AbortSignal } = {},
): Promise<UpcomingAnswer> {
  const qs = iso ? `?iso=${encodeURIComponent(iso)}` : ""
  const res = await apiFetch(`${API_BASE}/presence/upcoming${qs}`, { signal: options.signal })
  if (!res.ok) throw new Error(`GET /presence/upcoming ${res.status}`)
  return (await res.json()) as UpcomingAnswer
}

export async function fetchPlace(
  target: PlaceTarget,
  options: { signal?: AbortSignal } = {},
): Promise<PlaceAnswer | null> {
  const url = placeUrl(target, API_BASE)
  if (!url) return null
  const res = await apiFetch(url, { signal: options.signal })
  if (!res.ok) throw new Error(`place failed: ${res.status}`)
  return (await res.json()) as PlaceAnswer
}

/** Live aircraft (#873). Never stored, never citable — see `app/presence/`. */
/** Vessels broadcasting AIS (#954). Never stored, never citable, and covering
 *  one authority's receiver range rather than an ocean. */
export async function fetchPresenceVessels(
  options: { signal?: AbortSignal } = {},
): Promise<VesselAnswer> {
  const res = await apiFetch(`${API_BASE}/presence/vessels`, { signal: options.signal })
  if (!res.ok) throw new Error(`presence vessels failed: ${res.status}`)
  return (await res.json()) as VesselAnswer
}

export async function fetchPresenceAircraft(
  options: { signal?: AbortSignal } = {},
): Promise<PresenceAnswer> {
  const res = await apiFetch(`${API_BASE}/presence/aircraft`, { signal: options.signal })
  if (!res.ok) throw new Error(`presence failed: ${res.status}`)
  return (await res.json()) as PresenceAnswer
}
