"use client"

import { formatDistanceToNowStrict } from "date-fns"
import useSWR from "swr"
import { useEvents } from "@/app/providers"
import { fetchIngestHealth, fetchSourceCoverage, isApiConfigured } from "@/lib/apiClient"
import { cn } from "@/lib/utils"
import { summarizeSystemHealth, type DatasetHealthSummary } from "@/lib/systemHealth"
import type { IngestHealthRow, SourceCoverageRow } from "@/lib/types"
import { ConnectionIndicator } from "./ConnectionIndicator"

const API_REFRESH_MS = 30_000
const COVERAGE_REFRESH_MS = 60_000

interface SystemStatusBarProps {
  mapCount: number
  globeCount: number
}

function useIngestHealthRows(): IngestHealthRow[] {
  const { data } = useSWR(isApiConfigured ? "topbar-ingest-health" : null, () => fetchIngestHealth(7), {
    refreshInterval: API_REFRESH_MS,
    revalidateOnFocus: false,
  })
  return data ?? []
}

function useCoverageRows(): SourceCoverageRow[] {
  const { data } = useSWR(isApiConfigured ? "topbar-source-coverage" : null, () => fetchSourceCoverage(30), {
    refreshInterval: COVERAGE_REFRESH_MS,
    revalidateOnFocus: false,
  })
  return data ?? []
}

function statusClasses(status: DatasetHealthSummary["status"]): string {
  switch (status) {
    case "ok":
      return "border-emerald-800/80 bg-emerald-950/50 text-emerald-200"
    case "warn":
      return "border-amber-800/80 bg-amber-950/50 text-amber-200"
    case "stale":
      return "border-orange-800/80 bg-orange-950/50 text-orange-200"
    case "offline":
      return "border-red-800/80 bg-red-950/50 text-red-200"
  }
}

function statusDot(status: DatasetHealthSummary["status"]): string {
  switch (status) {
    case "ok":
      return "bg-emerald-400"
    case "warn":
      return "bg-amber-400"
    case "stale":
      return "bg-orange-400"
    case "offline":
      return "bg-red-400"
  }
}

function statusLabel(status: DatasetHealthSummary["status"]): string {
  switch (status) {
    case "ok":
      return "online"
    case "warn":
      return "degraded"
    case "stale":
      return "stale"
    case "offline":
      return "offline"
  }
}

export function SystemStatusBar({ mapCount, globeCount }: SystemStatusBarProps) {
  const events = useEvents()
  const ingestRows = useIngestHealthRows()
  const coverageRows = useCoverageRows()
  const datasets = summarizeSystemHealth(ingestRows, coverageRows)
  const latestTs = events[0]?.occurred_at ?? null
  const latestLabel = latestTs
    ? formatDistanceToNowStrict(new Date(latestTs), { addSuffix: true })
    : "no events yet"

  return (
    <div className="fixed inset-x-0 top-0 z-50 border-b border-neutral-800 bg-neutral-950/95 backdrop-blur-xl">
      <div className="mx-auto flex h-20 w-full max-w-[2400px] flex-col justify-center gap-2 px-3 sm:px-4">
        <div className="flex items-center gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="truncate font-mono text-[11px] font-medium uppercase tracking-[0.32em] text-neutral-100/85">
              OSINT World Monitor
            </span>
            <ConnectionIndicator />
          </div>

          <div className="ml-auto hidden items-center gap-3 md:flex">
            <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
              map {mapCount} · globe {globeCount}
            </span>
            <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
              latest {latestLabel}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {datasets.map((dataset) => (
            <span
              key={dataset.key}
              title={
                dataset.detail
                  ? `${dataset.label}: ${dataset.detail}`
                  : `${dataset.label}: ${statusLabel(dataset.status)}`
              }
              className={cn(
                "inline-flex shrink-0 items-center gap-2 rounded-md border px-2.5 py-1 font-mono text-[10px] uppercase tracking-widest",
                statusClasses(dataset.status),
              )}
            >
              <span className={cn("h-2 w-2 rounded-full", statusDot(dataset.status))} />
              <span className="text-neutral-100/80">{dataset.label}</span>
              <span className="text-neutral-100/60">{dataset.healthy}/{dataset.total}</span>
            </span>
          ))}
          <span className="ml-2 shrink-0 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
            {datasets.filter((d) => d.status !== "ok").length} source groups need attention
          </span>
        </div>
      </div>
    </div>
  )
}
