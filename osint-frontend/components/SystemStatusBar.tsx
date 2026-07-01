"use client"

import useSWR from "swr"
import { fetchIngestHealth, fetchSourceCoverage, isApiConfigured } from "@/lib/apiClient"
import { summarizeSystemHealth, type DatasetHealthSummary } from "@/lib/systemHealth"
import type { IngestHealthRow, SourceCoverageRow } from "@/lib/types"
import { ConnectionIndicator } from "./ConnectionIndicator"

const API_REFRESH_MS = 30_000
const COVERAGE_REFRESH_MS = 60_000

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

function statusTextClass(status: DatasetHealthSummary["status"]): string {
  switch (status) {
    case "ok":
      return "text-emerald-400"
    case "warn":
      return "text-amber-400"
    case "stale":
      return "text-orange-400"
    case "offline":
      return "text-red-400"
  }
}

export function SystemStatusBar() {
  const ingestRows = useIngestHealthRows()
  const coverageRows = useCoverageRows()
  const datasets = summarizeSystemHealth(ingestRows, coverageRows)

  return (
    <div className="fixed inset-x-0 top-0 z-50 border-b border-neutral-800 bg-neutral-950/96 backdrop-blur-xl">
      <div className="mx-auto flex min-h-9 w-full max-w-[2400px] flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1 sm:px-4">
        <ConnectionIndicator />
        <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-x-3 gap-y-1">
          {datasets.map((dataset) => (
            <span key={dataset.key} title={dataset.detail ?? `${dataset.label}: ${statusLabel(dataset.status)}`} className="font-mono text-[9px] uppercase tracking-widest text-neutral-400">
              <span className="text-neutral-200/80">{dataset.label}</span> <span className={statusTextClass(dataset.status)}>{statusLabel(dataset.status)}</span> <span className="text-neutral-500">{dataset.healthy}/{dataset.total}</span>
            </span>
          ))}
          <span className="font-mono text-[9px] uppercase tracking-widest text-neutral-500">
            {datasets.filter((d) => d.status !== "ok").length} attention
          </span>
        </div>
      </div>
    </div>
  )
}
