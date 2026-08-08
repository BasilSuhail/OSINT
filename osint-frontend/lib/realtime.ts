import { CLIENT_LIMITS, fetchEvents, streamUrl } from "./apiClient"
import { sourceKeyForEvent, type EventRow } from "./types"

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "polling"
  | "disconnected"

export interface ConnectionDiagnostics {
  status: ConnectionStatus
  reconnectAttempts: number
  /** Newest durable database revision represented in the client buffer. */
  lastEventAt: Date | null
  /** Last time we proved the realtime channel is alive (subscribed or got an event). */
  lastSeenAt: Date | null
}

export interface RevisionCursor {
  /** Raw API timestamp. Keep PostgreSQL microseconds; Date truncates them. */
  updatedAt: string
  id: string
}

const MAX_EVENTS = CLIENT_LIMITS.eventBuffer

const POLL_INTERVAL_MS = 30_000
const MAX_RECONNECT_BEFORE_POLL = 3
/** Coalesce a burst of ingests into one re-render. The snapshot updates
 *  synchronously; only subscriber notifications are throttled, so the map
 *  doesn't re-filter/-cluster on every fetch tick. */
const NOTIFY_THROTTLE_MS = 200

function eventRevision(row: EventRow): string {
  return JSON.stringify([
    row.source,
    row.source_event_id,
    row.occurred_at,
    row.fetched_at,
    row.updated_at,
    row.category,
    row.severity,
    row.keywords,
    row.country,
    row.lat,
    row.lon,
    row.payload,
  ])
}

function validTimeMs(value: unknown): number | null {
  if (typeof value !== "string") return null
  if (!value) return null
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? ms : null
}

function eventUpdateStamp(row: EventRow | undefined): string | null {
  if (!row) return null
  return row.updated_at ?? row.fetched_at ?? null
}

function idAfter(candidate: string, current: string): boolean {
  return candidate.length !== current.length
    ? candidate.length > current.length
    : candidate > current
}

function revisionAfter(candidate: RevisionCursor, current: RevisionCursor): boolean {
  const candidateMs = validTimeMs(candidate.updatedAt)
  const currentMs = validTimeMs(current.updatedAt)
  if (candidateMs === null || currentMs === null) return false
  if (candidateMs !== currentMs) return candidateMs > currentMs
  if (candidate.updatedAt !== current.updatedAt) return candidate.updatedAt > current.updatedAt
  return idAfter(candidate.id, current.id)
}

function timestampAfter(candidate: string, current: string): boolean {
  return revisionAfter(
    { updatedAt: candidate, id: "0" },
    { updatedAt: current, id: "0" },
  )
}

/** How much a row deserves its place when the buffer is full.
 *
 * The newer of event time and durable revision, so a story enriched a moment
 * ago survives a buffer full of newer events — that is the behaviour #763
 * added and it must stay.
 *
 * The revision only counts when this client actually saw it happen (#764).
 * Migration 0026 stamped 1,489,591 rows with one revision, and the live table
 * still carries that tie today. Under a plain `max()` every one of those
 * ancient rows scores as though it were revised at migration time, outranking
 * genuinely recent events and evicting them under the buffer cap. A bulk stamp
 * is evidence that a million rows were touched at once, not evidence that any
 * of them is fresh. */
function retentionTimeMs(row: EventRow, seenFromMs: number): number {
  const occurredMs = validTimeMs(row.occurred_at) ?? Number.NEGATIVE_INFINITY
  const updateMs = validTimeMs(eventUpdateStamp(row)) ?? Number.NEGATIVE_INFINITY
  return Math.max(occurredMs, updateMs >= seenFromMs ? updateMs : Number.NEGATIVE_INFINITY)
}

/** High-volume feeds kept OUT of the main firehose so they can't saturate the
 *  buffer and starve the sparse displayable sources (gdelt / news / gdacs).
 *  opensky-adsb (~190k/day) is never shown; NASA FIRMS (100k+) is globe-only
 *  and abuse.ch cyber (~20k) is dense — both are pulled separately, capped, by
 *  dedicated polls in the provider. */
export const FIREHOSE_EXCLUDE = [
  "opensky-adsb",
  "nasa-firms",
  "abuse-ch-urlhaus",
  "abuse-ch-feodo",
]

/**
 * In-memory ring buffer of the most recent events plus an SSE EventSource
 * subscription with polling fallback. Both panes read from the same buffer.
 * Components subscribe via `subscribe()` and receive an immutable snapshot
 * whenever it changes.
 *
 * Connection lifecycle:
 *   connecting → connected → (stream error) → reconnecting (EventSource retries automatically)
 *                         → polling (after MAX_RECONNECT_BEFORE_POLL errors)
 *                         → connected (if stream recovers)
 *
 * On every SSE open/message we backfill events via REST since `lastEventAt`
 * so the dashboard catches up to anything that landed during any outage.
 */
export class EventBuffer {
  /** When this client started watching. A revision older than this happened
   *  before anyone was looking, so it cannot be a live enrichment (#764). */
  private readonly startedAtMs: number = Date.now()
  private events: EventRow[] = []
  private byId = new Map<string, EventRow>()
  private revisions = new Map<string, string>()
  private listeners = new Set<() => void>()
  private statusListeners = new Set<(d: ConnectionDiagnostics) => void>()
  private source: EventSource | null = null
  private status: ConnectionStatus = "connecting"
  private snapshot: EventRow[] = []
  private reconnectAttempts = 0
  private lastEventAt: Date | null = null
  private revisionCursor: RevisionCursor | null = null
  private lastSeenAt: Date | null = null

  private pollTimer: ReturnType<typeof setInterval> | null = null
  private notifyTimer: ReturnType<typeof setTimeout> | null = null
  private stopped = false

  /** Seed/merge a batch of events (e.g. from the initial query or SWR refetch). */
  ingest(rows: EventRow[], retainIds: ReadonlySet<string> = new Set()): void {
    let changed = false
    for (const row of rows) {
      if (!row?.id) continue
      // Skip events with no source toggle (aviation/cyber/etc.). They are
      // never rendered from this buffer, and high-frequency feeds like
      // opensky-adsb (~190k rows/day) would otherwise flood the live stream
      // and evict every displayable event under the MAX_EVENTS cap.
      if (sourceKeyForEvent(row) === null) continue
      const revision = eventRevision(row)
      // Snapshot sources refresh hazards in place, and enrichment can move an
      // RSS row from a city anchor to a verified building without changing its
      // database ID. Treat ID as identity, not immutability: replace any row
      // whose render-relevant representation changed. A stable serialization
      // prevents the 30-second full-window poll from repainting unchanged data.
      if (this.revisions.get(row.id) === revision) continue
      const stored = this.byId.get(row.id)
      const incomingUpdate = eventUpdateStamp(row)
      const storedUpdate = eventUpdateStamp(stored)
      // SWR, SSE backfills, and polling can resolve out of order. Never let an
      // older valid snapshot roll exact coordinates/provenance back after a
      // newer enrichment revision has already reached the buffer.
      if (
        incomingUpdate !== null &&
        storedUpdate !== null &&
        timestampAfter(storedUpdate, incomingUpdate)
      ) {
        continue
      }
      this.byId.set(row.id, row)
      this.revisions.set(row.id, revision)
      changed = true
    }
    if (!changed) return
    this.events = [...this.byId.values()]
    if (this.events.length > MAX_EVENTS) {
      // A freshly enriched older story must survive a full recent-event buffer.
      // Retention uses the newer of event time and durable revision, while the
      // published snapshot remains ordered by the event's actual occurrence.
      this.events.sort((a, b) => {
        const protectedOrder = Number(retainIds.has(b.id)) - Number(retainIds.has(a.id))
        return (
          protectedOrder ||
          retentionTimeMs(b, this.startedAtMs) - retentionTimeMs(a, this.startedAtMs)
        )
      })
      const removed = this.events.splice(MAX_EVENTS)
      for (const r of removed) {
        this.byId.delete(r.id)
        this.revisions.delete(r.id)
      }
    }
    this.events.sort((a, b) => +new Date(b.occurred_at) - +new Date(a.occurred_at))
    this.commit()
  }

  /** Merge one ordered incremental page and advance only its durable cursor.
   * Snapshot/hazard/cyber pulls must never move this cursor: they do not prove
   * that every earlier revision from the incremental source was consumed. */
  ingestUpdated(rows: EventRow[]): void {
    this.ingest(rows, new Set(rows.map((row) => row.id)))
    for (const row of rows) {
      if (!row.updated_at || validTimeMs(row.updated_at) === null) continue
      const candidate = { updatedAt: row.updated_at, id: row.id }
      if (!this.revisionCursor || revisionAfter(candidate, this.revisionCursor)) {
        this.revisionCursor = candidate
      }
    }
    this.lastEventAt = this.revisionCursor
      ? new Date(this.revisionCursor.updatedAt)
      : this.lastEventAt
  }

  private commit(): void {
    // Snapshot updates synchronously so getSnapshot() is always current; the
    // subscriber notification (which drives React re-renders) is throttled.
    this.snapshot = this.events.slice()
    if (this.notifyTimer) return
    this.notifyTimer = setTimeout(() => {
      this.notifyTimer = null
      for (const l of this.listeners) l()
    }, NOTIFY_THROTTLE_MS)
  }

  getSnapshot = (): EventRow[] => this.snapshot

  getStatus = (): ConnectionStatus => this.status

  getRevisionCursor = (): RevisionCursor | null => this.revisionCursor

  getDiagnostics = (): ConnectionDiagnostics => ({
    status: this.status,
    reconnectAttempts: this.reconnectAttempts,
    lastEventAt: this.lastEventAt,
    lastSeenAt: this.lastSeenAt,
  })

  subscribe = (cb: () => void): (() => void) => {
    this.listeners.add(cb)
    return () => this.listeners.delete(cb)
  }

  subscribeStatus = (cb: (d: ConnectionDiagnostics) => void): (() => void) => {
    this.statusListeners.add(cb)
    return () => this.statusListeners.delete(cb)
  }

  private setStatus(s: ConnectionStatus): void {
    if (this.status === s) return
    this.status = s
    const diag = this.getDiagnostics()
    for (const l of this.statusListeners) l(diag)
  }

  /** Open the SSE stream. EventSource auto-reconnects, so no manual backoff. */
  connect(): void {
    this.stopped = false
    if (this.source) return
    this.setStatus("connecting")
    const es = new EventSource(streamUrl())
    this.source = es
    es.onopen = () => {
      this.lastSeenAt = new Date()
      this.setStatus("connected")
      this.reconnectAttempts = 0
      this.stopPolling()
      void this.backfillSinceLastSeen()
    }
    es.onmessage = () => {
      this.lastSeenAt = new Date()
      void this.backfillSinceLastSeen()
    }
    es.onerror = () => {
      // EventSource retries on its own; surface the state + arm the poll
      // fallback so data still flows if the stream stays down.
      this.setStatus(this.reconnectAttempts >= MAX_RECONNECT_BEFORE_POLL ? "polling" : "reconnecting")
      this.reconnectAttempts += 1
      if (this.reconnectAttempts >= MAX_RECONNECT_BEFORE_POLL) this.startPolling()
    }
  }

  private startPolling(): void {
    if (this.pollTimer) return
    this.pollTimer = setInterval(() => {
      void this.backfillSinceLastSeen()
    }, POLL_INTERVAL_MS)
    // Immediate pull so the user doesn't stare at stale data for a full
    // poll interval after the demotion.
    void this.backfillSinceLastSeen()
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer)
      this.pollTimer = null
    }
  }

  /**
   * Pull events since `lastEventAt` via REST and merge into the buffer. Used
   * during polling fallback and immediately after a successful reconnect.
   */
  private async backfillSinceLastSeen(): Promise<void> {
    const cursor = this.revisionCursor
    const watermark = cursor
      ? cursor.updatedAt
      : new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
    try {
      const rows = await fetchEvents({
        updatedSince: watermark,
        updatedAfterId: cursor?.id,
        exclude: FIREHOSE_EXCLUDE,
        limit: 2000,
      })
      if (rows.length) this.ingestUpdated(rows)
    } catch {
      // Network blip; next SSE message or poll tick retries.
    }
  }

  disconnect(): void {
    this.stopped = true
    this.stopPolling()
    if (this.notifyTimer) {
      clearTimeout(this.notifyTimer)
      this.notifyTimer = null
    }
    if (this.source) {
      this.source.close()
      this.source = null
    }
    this.setStatus("disconnected")
  }
}
