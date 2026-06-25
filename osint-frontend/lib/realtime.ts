import { fetchEvents, streamUrl } from "./apiClient"
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
  /** Last time an event of any kind arrived (insert or polled). */
  lastEventAt: Date | null
  /** Last time we proved the realtime channel is alive (subscribed or got an event). */
  lastSeenAt: Date | null
}

const MAX_EVENTS = 5000

const POLL_INTERVAL_MS = 30_000
const MAX_RECONNECT_BEFORE_POLL = 3

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
  private events: EventRow[] = []
  private byId = new Set<string>()
  private listeners = new Set<() => void>()
  private statusListeners = new Set<(d: ConnectionDiagnostics) => void>()
  private source: EventSource | null = null
  private status: ConnectionStatus = "connecting"
  private snapshot: EventRow[] = []
  private reconnectAttempts = 0
  private lastEventAt: Date | null = null
  private lastSeenAt: Date | null = null

  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private pollTimer: ReturnType<typeof setInterval> | null = null
  private stopped = false

  /** Seed/merge a batch of events (e.g. from the initial query or SWR refetch). */
  ingest(rows: EventRow[]): void {
    let changed = false
    for (const row of rows) {
      if (!row?.id || this.byId.has(row.id)) continue
      // Skip events with no source toggle (aviation/cyber/etc.). They are
      // never rendered from this buffer, and high-frequency feeds like
      // opensky-adsb (~190k rows/day) would otherwise flood the live stream
      // and evict every displayable event under the MAX_EVENTS cap.
      if (sourceKeyForEvent(row) === null) continue
      this.byId.add(row.id)
      this.events.push(row)
      this.lastEventAt = new Date()
      changed = true
    }
    if (!changed) return
    this.events.sort((a, b) => +new Date(b.occurred_at) - +new Date(a.occurred_at))
    if (this.events.length > MAX_EVENTS) {
      const removed = this.events.splice(MAX_EVENTS)
      for (const r of removed) this.byId.delete(r.id)
    }
    this.commit()
  }

  private commit(): void {
    this.snapshot = this.events.slice()
    for (const l of this.listeners) l()
  }

  getSnapshot = (): EventRow[] => this.snapshot

  getStatus = (): ConnectionStatus => this.status

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

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
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
    const since = this.lastEventAt
      ? this.lastEventAt.toISOString()
      : new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
    try {
      const rows = await fetchEvents({ since, exclude: ["opensky-adsb"], limit: 500 })
      if (rows.length) this.ingest(rows)
    } catch {
      // Network blip; next SSE message or poll tick retries.
    }
  }

  disconnect(): void {
    this.stopped = true
    this.stopHeartbeat()
    this.stopPolling()
    if (this.source) {
      this.source.close()
      this.source = null
    }
    this.setStatus("disconnected")
  }
}
