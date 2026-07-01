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
  const statusTokens = datasets.map((dataset) => ({
    ...dataset,
    compactStatus: {
      ok: "on",
      warn: "degraded",
      stale: "stale",
      offline: "off",
    }[dataset.status],
  }))

  return (
    <div className="sticky top-0 z-50 h-7 border-b border-neutral-800 bg-neutral-950/96 backdrop-blur-xl">
      <div className="mx-auto flex min-h-7 w-full max-w-[1800px] flex-nowrap items-center gap-x-2 px-2 py-0.5">
        <ConnectionIndicator />
        <div className="ml-auto flex min-w-0 flex-nowrap items-center gap-x-2 overflow-hidden">
          {statusTokens.map((dataset) => (
            <span
              key={dataset.key}
              title={dataset.detail ?? `${dataset.label}: ${statusLabel(dataset.status)}`}
              className="shrink-0 whitespace-nowrap font-mono text-[8px] uppercase tracking-widest text-neutral-500"
            >
              <span className="text-neutral-100/80">{dataset.label}</span>{" "}
              <span className={statusTextClass(dataset.status)}>{dataset.compactStatus}</span>{" "}
              <span className="text-neutral-500">
                {dataset.healthy}/{dataset.total}
              </span>
            </span>
          ))}
          <span className="shrink-0 whitespace-nowrap font-mono text-[8px] uppercase tracking-widest text-neutral-500">
            {datasets.filter((d) => d.status !== "ok").length} attention
          </span>
        </div>
      </div>
    </div>
  )
}
