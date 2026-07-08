import { API_BASE } from "./apiClient"

export interface StoryRow {
  id: string
  title: string
  first_seen: string
  last_seen: string
  member_count: number
  outlet_count: number
  method_version: string
}

export async function fetchTopStories(hours = 24, limit = 100): Promise<StoryRow[]> {
  const res = await fetch(`${API_BASE}/stories/top?hours=${hours}&limit=${limit}`)
  if (!res.ok) throw new Error(`GET /stories/top ${res.status}`)
  return (await res.json()) as StoryRow[]
}

export interface ScoreboardLine {
  source: string
  method_version: string
  horizon_months: number
  issued: number
  graded: number
  pending: number
  positive_rate: number | null
  mean_score: number | null
  brier: number | null
}

export async function fetchScoreboard(): Promise<ScoreboardLine[]> {
  const res = await fetch(`${API_BASE}/journal/scoreboard`)
  if (!res.ok) throw new Error(`GET /journal/scoreboard ${res.status}`)
  return (await res.json()) as ScoreboardLine[]
}

export interface BaselineResultRow {
  baseline: string
  horizon_months: number
  n: number
  positive_rate: number | null
  auroc: number | null
  aupr: number | null
  brier: number | null
}

export interface BaselinesReport {
  generated_at: string
  eval_window: [string, string]
  code_positive_rates: Record<string, number>
  results: BaselineResultRow[]
  head_to_head_common_support: BaselineResultRow[]
}

export async function fetchBaselinesReport(): Promise<BaselinesReport> {
  const res = await fetch(`${API_BASE}/analytics/baselines`)
  if (!res.ok) throw new Error(`GET /analytics/baselines ${res.status}`)
  return (await res.json()) as BaselinesReport
}

export interface CoverageStat {
  country: string
  coverage_months: number
  observed_months: number
  total_events: number
  events_per_month: number
  global_share: number
  fatalities_per_event: number
  baseline_std: number
}

export interface CoverageReport {
  generated_at: string
  countries: number
  global_events: number
  top_share: Record<string, number>
  stats: CoverageStat[]
}

export async function fetchCoverageReport(): Promise<CoverageReport> {
  const res = await fetch(`${API_BASE}/analytics/coverage`)
  if (!res.ok) throw new Error(`GET /analytics/coverage ${res.status}`)
  return (await res.json()) as CoverageReport
}

export interface JobRun {
  id: number
  job: string
  status: "running" | "done" | "failed"
  started_at: string
  heartbeat_at: string
  finished_at: string | null
  progress: string | null
  detail: string | null
}

export async function fetchRecentJobs(hours = 48): Promise<JobRun[]> {
  const res = await fetch(`${API_BASE}/jobs/recent?hours=${hours}`)
  if (!res.ok) throw new Error(`GET /jobs/recent ${res.status}`)
  return (await res.json()) as JobRun[]
}
