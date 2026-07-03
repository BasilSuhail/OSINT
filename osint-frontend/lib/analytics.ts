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
