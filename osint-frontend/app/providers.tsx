"use client"

import { createContext, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import useSWR from "swr"
import { EventBuffer, type ConnectionStatus } from "@/lib/realtime"
import { getSupabase, isSupabaseConfigured } from "@/lib/supabase"
import type { EventRow } from "@/lib/types"

interface RealtimeContextValue {
  buffer: EventBuffer
  configured: boolean
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null)

const WINDOW_MS = 30 * 24 * 60 * 60 * 1000 // 30 days

async function fetchRecentEvents(): Promise<EventRow[]> {
  const supabase = getSupabase()
  if (!supabase) return []
  const since = new Date(Date.now() - WINDOW_MS).toISOString()
  const { data, error } = await supabase
    .from("events")
    .select("*")
    .gte("occurred_at", since)
    .order("occurred_at", { ascending: false })
    .limit(5000)
  if (error) throw error
  return (data ?? []) as EventRow[]
}

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const bufferRef = useRef<EventBuffer | null>(null)
  if (!bufferRef.current) bufferRef.current = new EventBuffer()
  const buffer = bufferRef.current

  useEffect(() => {
    if (!isSupabaseConfigured) return
    buffer.connect()
    return () => buffer.disconnect()
  }, [buffer])

  // SWR fallback: poll every 30s (and once on mount) to backfill / recover.
  useSWR(isSupabaseConfigured ? "events-window" : null, fetchRecentEvents, {
    refreshInterval: 30_000,
    revalidateOnFocus: false,
    onSuccess: (rows) => buffer.ingest(rows),
  })

  const value = useMemo<RealtimeContextValue>(
    () => ({ buffer, configured: isSupabaseConfigured }),
    [buffer],
  )

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>
}

function useRealtime(): RealtimeContextValue {
  const ctx = useContext(RealtimeContext)
  if (!ctx) throw new Error("useRealtime must be used within RealtimeProvider")
  return ctx
}

/** Subscribe to the shared event buffer (re-renders on change). */
export function useEvents(): EventRow[] {
  const { buffer } = useRealtime()
  return useSyncExternalStore(buffer.subscribe, buffer.getSnapshot, () => buffer.getSnapshot())
}

/** Subscribe to the realtime connection status. */
export function useConnectionStatus(): ConnectionStatus {
  const { buffer, configured } = useRealtime()
  const [status, setStatus] = useState<ConnectionStatus>(
    configured ? buffer.getStatus() : "disconnected",
  )
  useEffect(() => {
    if (!configured) return
    setStatus(buffer.getStatus())
    return buffer.subscribeStatus(setStatus)
  }, [buffer, configured])
  return status
}

export function useConfigured(): boolean {
  return useRealtime().configured
}
