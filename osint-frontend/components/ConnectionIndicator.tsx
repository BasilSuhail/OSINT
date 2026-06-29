"use client"

import { formatDistanceToNowStrict } from "date-fns"
import { useConnectionDiagnostics } from "@/app/providers"

const META: Record<
  string,
  { color: string; label: string; pulse: boolean; longLabel: string }
> = {
  connected: {
    color: "bg-emerald-500",
    label: "online",
    longLabel: "Realtime channel connected",
    pulse: false,
  },
  connecting: {
    color: "bg-amber-500",
    label: "connecting",
    longLabel: "Opening realtime channel…",
    pulse: true,
  },
  reconnecting: {
    color: "bg-amber-500",
    label: "retrying",
    longLabel: "Realtime channel stalled — backing off and retrying",
    pulse: true,
  },
  polling: {
    color: "bg-amber-500",
    label: "polling",
    longLabel: "Realtime unavailable — polling REST every 30 s",
    pulse: true,
  },
  disconnected: {
    color: "bg-red-500",
    label: "offline",
    longLabel: "Disconnected from live stream",
    pulse: false,
  },
}

export function ConnectionIndicator() {
  const diag = useConnectionDiagnostics()
  const meta = META[diag.status] ?? META.disconnected
  const lastEvent = diag.lastEventAt
    ? formatDistanceToNowStrict(diag.lastEventAt, { addSuffix: true })
    : "—"

  const tooltip = [
    meta.longLabel,
    `Last event: ${lastEvent}`,
    diag.reconnectAttempts > 0 ? `Reconnects: ${diag.reconnectAttempts}` : null,
  ]
    .filter(Boolean)
    .join("\n")

  return (
    <span title={tooltip} className="font-mono text-[9px] uppercase tracking-widest text-neutral-400">
      realtime <span className={meta.color.replace("bg-", "text-")}>{meta.label}</span>
    </span>
  )
}
