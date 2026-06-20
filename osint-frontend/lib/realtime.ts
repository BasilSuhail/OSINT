import type { RealtimeChannel } from "@supabase/supabase-js"
import { getSupabase } from "./supabase"
import type { EventRow } from "./types"

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

const HEARTBEAT_INTERVAL_MS = 20_000
const HEARTBEAT_TIMEOUT_MS = 5_000
const POLL_INTERVAL_MS = 30_000
const MAX_RECONNECT_BEFORE_POLL = 3
// Exponential backoff between reconnect attempts.
const BACKOFF_SCHEDULE_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000]

function backoffMs(attempt: number): number {
  const idx = Math.min(attempt, BACKOFF_SCHEDULE_MS.length - 1)
  return BACKOFF_SCHEDULE_MS[idx]
}

/**
 * In-memory ring buffer of the most recent events plus a Supabase Realtime
 * subscription with heartbeat + reconnect + polling fallback. Both panes read
 * from the same buffer. Components subscribe via `subscribe()` and receive an
 * immutable snapshot whenever it changes.
 *
 * Connection lifecycle:
 *   connecting → connected → (silent channel) → reconnecting (exponential backoff)
 *                         → polling (after 3 failed reconnects)
 *                         → connected (if any later reconnect succeeds)
 *
 * On every successful reconnect we backfill events via REST since `lastEventAt`
 * so the dashboard catches up to anything that landed during the outage.
 */
export class EventBuffer {
  private events: EventRow[] = []
  private byId = new Set<string>()
  private listeners = new Set<() => void>()
  private statusListeners = new Set<(d: ConnectionDiagnostics) => void>()
  private channel: RealtimeChannel | null = null
  private status: ConnectionStatus = "connecting"
  private snapshot: EventRow[] = []
  private reconnectAttempts = 0
  private lastEventAt: Date | null = null
  private lastSeenAt: Date | null = null

  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private pollTimer: ReturnType<typeof setInterval> | null = null
  private stopped = false

  /** Seed/merge a batch of events (e.g. from the initial query or SWR refetch). */
  ingest(rows: EventRow[]): void {
    let changed = false
    for (const row of rows) {
      if (!row?.id || this.byId.has(row.id)) continue
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

  /** Open the realtime channel + start the heartbeat. Idempotent. */
  connect(): void {
    this.stopped = false
    const supabase = getSupabase()
    if (!supabase || this.channel) return

    this.setStatus(this.reconnectAttempts > 0 ? "reconnecting" : "connecting")
    this.channel = supabase
      .channel("events-realtime")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "events" },
        (payload) => {
          this.lastSeenAt = new Date()
          this.ingest([payload.new as EventRow])
        },
      )
      .subscribe((status) => {
        if (status === "SUBSCRIBED") {
          this.lastSeenAt = new Date()
          this.setStatus("connected")
          if (this.reconnectAttempts > 0) {
            this.backfillSinceLastSeen().catch(() => {})
          }
          this.reconnectAttempts = 0
          this.stopPolling()
          this.startHeartbeat()
        } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
          this.scheduleReconnect()
        } else if (status === "CLOSED") {
          if (!this.stopped) this.scheduleReconnect()
        }
      })
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => this.pingHeartbeat(), HEARTBEAT_INTERVAL_MS)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  /**
   * Best-effort liveness check: if `lastSeenAt` has gone quiet for more than
   * one heartbeat interval, the channel is considered stalled and we cycle
   * back to reconnect. (Supabase Realtime sends presence diffs + pings under
   * the hood; absence of any traffic for ~25 s is suspicious.)
   */
  private pingHeartbeat(): void {
    if (this.stopped) return
    const last = this.lastSeenAt?.getTime() ?? 0
    if (last === 0) {
      this.scheduleReconnect()
      return
    }
    if (Date.now() - last > HEARTBEAT_INTERVAL_MS + HEARTBEAT_TIMEOUT_MS) {
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return
    this.stopHeartbeat()
    const supabase = getSupabase()
    if (supabase && this.channel) {
      supabase.removeChannel(this.channel)
      this.channel = null
    }
    if (this.reconnectAttempts >= MAX_RECONNECT_BEFORE_POLL) {
      this.setStatus("polling")
      this.startPolling()
    } else {
      this.setStatus("reconnecting")
    }
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts += 1
      this.connect()
    }, backoffMs(this.reconnectAttempts))
  }

  private startPolling(): void {
    if (this.pollTimer) return
    this.pollTimer = setInterval(() => {
      this.backfillSinceLastSeen().catch(() => {})
    }, POLL_INTERVAL_MS)
    // Immediate pull so the user doesn't stare at stale data for a full
    // poll interval after the demotion.
    this.backfillSinceLastSeen().catch(() => {})
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
    const supabase = getSupabase()
    if (!supabase) return
    const since = this.lastEventAt
      ? this.lastEventAt.toISOString()
      : new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
    try {
      const { data, error } = await supabase
        .from("events")
        .select("*")
        .gt("fetched_at", since)
        .order("occurred_at", { ascending: false })
        .limit(500)
      if (error) return
      if (data && data.length) this.ingest(data as EventRow[])
    } catch {
      // Network blip; next poll tick will retry.
    }
  }

  disconnect(): void {
    this.stopped = true
    this.stopHeartbeat()
    this.stopPolling()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    const supabase = getSupabase()
    if (this.channel && supabase) {
      supabase.removeChannel(this.channel)
      this.channel = null
    }
    this.setStatus("disconnected")
  }
}
