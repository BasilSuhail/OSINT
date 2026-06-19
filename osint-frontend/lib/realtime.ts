import type { RealtimeChannel } from "@supabase/supabase-js"
import { getSupabase } from "./supabase"
import type { EventRow } from "./types"

export type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "disconnected"

const MAX_EVENTS = 5000

/**
 * In-memory ring buffer of the most recent events plus a Supabase Realtime
 * subscription. Both panes read from the same buffer. Components subscribe via
 * `subscribe()` and receive an immutable snapshot whenever it changes.
 */
export class EventBuffer {
  private events: EventRow[] = []
  private byId = new Set<string>()
  private listeners = new Set<() => void>()
  private statusListeners = new Set<(s: ConnectionStatus) => void>()
  private channel: RealtimeChannel | null = null
  private status: ConnectionStatus = "connecting"
  private snapshot: EventRow[] = []

  /** Seed/merge a batch of events (e.g. from the initial query or SWR refetch). */
  ingest(rows: EventRow[]): void {
    let changed = false
    for (const row of rows) {
      if (!row?.id || this.byId.has(row.id)) continue
      this.byId.add(row.id)
      this.events.push(row)
      changed = true
    }
    if (!changed) return
    // Keep newest first, cap to MAX_EVENTS.
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

  subscribe = (cb: () => void): (() => void) => {
    this.listeners.add(cb)
    return () => this.listeners.delete(cb)
  }

  subscribeStatus = (cb: (s: ConnectionStatus) => void): (() => void) => {
    this.statusListeners.add(cb)
    return () => this.statusListeners.delete(cb)
  }

  private setStatus(s: ConnectionStatus): void {
    if (this.status === s) return
    this.status = s
    for (const l of this.statusListeners) l(s)
  }

  /** Open the realtime channel. Safe to call once. */
  connect(): void {
    const supabase = getSupabase()
    if (!supabase || this.channel) return

    this.setStatus("connecting")
    this.channel = supabase
      .channel("events-realtime")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "events" },
        (payload) => {
          this.ingest([payload.new as EventRow])
        },
      )
      .subscribe((status) => {
        if (status === "SUBSCRIBED") this.setStatus("connected")
        else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") this.setStatus("reconnecting")
        else if (status === "CLOSED") this.setStatus("disconnected")
      })
  }

  disconnect(): void {
    const supabase = getSupabase()
    if (this.channel && supabase) {
      supabase.removeChannel(this.channel)
      this.channel = null
    }
    this.setStatus("disconnected")
  }
}
