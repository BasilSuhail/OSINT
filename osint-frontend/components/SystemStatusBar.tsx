"use client"

import { useState } from "react"
import useSWR from "swr"
import {
  fetchBrainNarrative,
  fetchIngestHealth,
  fetchSourceCoverage,
  isApiConfigured,
} from "@/lib/apiClient"
import { summarizeSystemHealth, type DatasetHealthSummary } from "@/lib/systemHealth"
import type { IngestHealthRow, SourceCoverageRow } from "@/lib/types"
import type { FilterStore } from "@/stores/createFilterStore"
import { ConnectionIndicator } from "./ConnectionIndicator"
import { JobChips } from "./JobChips"
import { TimeWindowStatus } from "./TimeWindowStatus"

const API_REFRESH_MS = 30_000
const COVERAGE_REFRESH_MS = 60_000
const BRAIN_REFRESH_MS = 30_000
const BRAIN_STALE_MS = 40 * 60_000

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

function useBrainStatus() {
  const { data } = useSWR(isApiConfigured ? "topbar-brain-narrative" : null, fetchBrainNarrative, {
    refreshInterval: BRAIN_REFRESH_MS,
    revalidateOnFocus: false,
  })
  return data ?? null
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

interface SystemStatusBarProps {
  /** The pane store driving the map's time scrubber (#501). */
  useStore: FilterStore
}

export function SystemStatusBar({ useStore }: SystemStatusBarProps) {
  const [open, setOpen] = useState(false)
  const ingestRows = useIngestHealthRows()
  const coverageRows = useCoverageRows()
  const brain = useBrainStatus()
  const datasets = summarizeSystemHealth(ingestRows, coverageRows)
  const createdAtMs = brain?.created_at ? new Date(brain.created_at).getTime() : null
  const brainStale =
    !brain?.present ||
    createdAtMs == null ||
    !Number.isFinite(createdAtMs) ||
    Date.now() - createdAtMs > BRAIN_STALE_MS
  const brainLabel = brainStale ? "sleep" : "working"
  const brainClass = brainStale ? "text-amber-400" : "text-emerald-400"
  const attention = datasets.filter((d) => d.status !== "ok").length
  const priorityDatasets = datasets.filter((d) => d.status !== "ok")
  const detailDatasets = priorityDatasets.length > 0 ? priorityDatasets : datasets

  return (
    <div className="sticky top-0 z-50 border-b border-neutral-800 bg-neutral-950/96 backdrop-blur-xl">
      <div className="relative mx-auto flex min-h-10 w-full max-w-[2400px] items-center gap-2 px-2 py-1.5 sm:px-3">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="shrink-0 rounded-md border border-neutral-800 bg-neutral-900/80 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.24em] text-neutral-400 hover:text-neutral-200"
          aria-expanded={open}
          aria-label="Toggle system detail"
        >
          ...
        </button>
        <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <ConnectionIndicator />
          <TimeWindowStatus useStore={useStore} />
          <span className="shrink-0 rounded-full border border-neutral-800 bg-neutral-900/70 px-2 py-1 font-mono text-[8px] uppercase tracking-wide text-neutral-400">
            AI <span className={brainClass}>{brainLabel}</span>
          </span>
          {datasets.map((dataset) => (
            <span
              key={dataset.key}
              title={dataset.detail ?? `${dataset.label}: ${statusLabel(dataset.status)}`}
              className="shrink-0 rounded-full border border-neutral-800/80 bg-neutral-900/60 px-2 py-1 font-mono text-[8px] uppercase tracking-wide text-neutral-400"
            >
              <span className="text-neutral-200/80">{dataset.label}</span>{" "}
              <span className={statusTextClass(dataset.status)}>{statusLabel(dataset.status)}</span>{" "}
              <span className="text-neutral-500">{dataset.healthy}/{dataset.total}</span>
            </span>
          ))}
          <JobChips />
        </div>
        <span className="shrink-0 pl-1 font-mono text-[8px] uppercase tracking-wide text-neutral-500">
          {attention} attention
        </span>
        {open ? (
          <div className="absolute left-2 top-[calc(100%+0.35rem)] z-50 w-[min(28rem,calc(100vw-1rem))] rounded-xl border border-neutral-800 bg-neutral-950/98 p-3 shadow-2xl shadow-black/40">
            <div className="mb-2 flex items-center justify-between">
              <p className="font-mono text-[9px] uppercase tracking-[0.24em] text-neutral-500">
                activity monitor
              </p>
              <span className="font-mono text-[9px] uppercase tracking-wide text-neutral-600">
                {attention} attention
              </span>
            </div>
            <div className="mb-3 rounded-lg border border-neutral-800 bg-neutral-900/60 p-2.5">
              <div className="mb-1 flex items-center gap-2 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
                <span>AI</span>
                <span className={brainClass}>{brainLabel}</span>
              </div>
              <p className="text-[11px] leading-snug text-neutral-300">
                {brain?.payload?.system ?? "No pipeline summary from the brain yet."}
                {brain?.created_at ? ` · ${new Date(brain.created_at).toLocaleTimeString()}` : ""}
              </p>
            </div>
            <div className="space-y-2">
              {detailDatasets.map((dataset) => (
                <div
                  key={dataset.key}
                  className="rounded-lg border border-neutral-800 bg-neutral-900/40 px-2.5 py-2"
                >
                  <div className="flex items-center justify-between gap-3 font-mono text-[9px] uppercase tracking-wide">
                    <span className="text-neutral-300">{dataset.label}</span>
                    <span className={statusTextClass(dataset.status)}>{statusLabel(dataset.status)}</span>
                  </div>
                  <p className="mt-1 text-[11px] leading-snug text-neutral-500">
                    {dataset.detail || "No detail"}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
