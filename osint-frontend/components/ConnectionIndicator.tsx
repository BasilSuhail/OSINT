"use client"

import { useConnectionStatus } from "@/app/providers"
import { cn } from "@/lib/utils"

const META: Record<string, { color: string; label: string; pulse: boolean }> = {
  connected: { color: "bg-emerald-500", label: "realtime", pulse: false },
  connecting: { color: "bg-amber-500", label: "connecting", pulse: true },
  reconnecting: { color: "bg-amber-500", label: "reconnecting", pulse: true },
  disconnected: { color: "bg-red-500", label: "offline · polling", pulse: false },
}

export function ConnectionIndicator() {
  const status = useConnectionStatus()
  const meta = META[status] ?? META.disconnected

  return (
    <div className="flex items-center gap-2 rounded-md border border-neutral-800 bg-neutral-950/70 px-2.5 py-1.5 backdrop-blur-sm">
      <span className="relative flex h-2 w-2">
        {meta.pulse && (
          <span
            className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-75", meta.color)}
          />
        )}
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", meta.color)} />
      </span>
      <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
        {meta.label}
      </span>
    </div>
  )
}
