import { API_BASE } from "./apiClient"

export interface StoryRow {
  id: string
  title: string
  first_seen: string
  last_seen: string
  member_count: number
  outlet_count: number
  owner_count: number
  corroboration: number | null
  corroboration_components: Record<string, unknown> | null
  sensor_checks: Record<string, string>
  method_version: string
  gist: string | null
  category: string | null
  escalating: string | null
}

/** Badge tone for the corroboration-v1.0 score (null = not yet scored). */
export function corroborationTone(score: number | null): string {
  if (score !== null && score >= 0.75) return "border-cyan-500/50 bg-cyan-500/10 text-cyan-300"
  if (score !== null && score >= 0.5)
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
  if (score !== null && score > 0) return "border-neutral-600 bg-neutral-800/60 text-neutral-300"
  return "border-neutral-800 bg-neutral-900 text-neutral-500"
}

export interface CorroborationTier {
  label: string
  detail: string
  count: number
  tone: string
}

/** Bucket stories into the four named confidence tiers the badge colours encode. */
export function corroborationTiers(stories: StoryRow[]): CorroborationTier[] {
  const tiers: CorroborationTier[] = [
    {
      label: "unverified — single teller",
      detail: "score 0: one organisation, nothing confirms it. A rumour until proven otherwise.",
      count: 0,
      tone: "bg-neutral-600",
    },
    {
      label: "weakly corroborated",
      detail: "score below 0.5: some independent confirmation exists, but thin.",
      count: 0,
      tone: "bg-neutral-400",
    },
    {
      label: "well corroborated",
      detail: "score 0.5 to 0.75: several independent organisations tell this story.",
      count: 0,
      tone: "bg-emerald-400",
    },
    {
      label: "strong — many tellers / sensor-backed",
      detail: "score 0.75+: many independent tellers, often confirmed by physical sensors.",
      count: 0,
      tone: "bg-cyan-400",
    },
  ]
  for (const s of stories) {
    const score = s.corroboration ?? 0
    if (score >= 0.75) tiers[3].count += 1
    else if (score >= 0.5) tiers[2].count += 1
    else if (score > 0) tiers[1].count += 1
    else tiers[0].count += 1
  }
  return tiers
}

/** Claim types the physical sensors confirmed — the ✓ chips on the story line. */
export function confirmedClaims(checks: Record<string, string>): string[] {
  return Object.entries(checks)
    .filter(([, verdict]) => verdict === "confirmed")
    .map(([claim]) => claim)
    .sort()
}

export async function fetchTopStories(hours = 24, limit = 100): Promise<StoryRow[]> {
  const res = await fetch(`${API_BASE}/stories/top?hours=${hours}&limit=${limit}`)
  if (!res.ok) throw new Error(`GET /stories/top ${res.status}`)
  return (await res.json()) as StoryRow[]
}

export interface StoryMember {
  title: string
  source: string
  outlet: string
  owner: string
  origin_country: string | null
  occurred_at: string
  similarity: number
}

export async function fetchStoryMembers(storyId: string): Promise<StoryMember[]> {
  const res = await fetch(`${API_BASE}/stories/${storyId}/members`)
  if (!res.ok) throw new Error(`GET /stories/${storyId}/members ${res.status}`)
  return (await res.json()) as StoryMember[]
}

export interface JournalMonthly {
  source: string
  month: string
  issued: number
  graded: number
  brier: number | null
}

export async function fetchJournalMonthly(): Promise<JournalMonthly[]> {
  const res = await fetch(`${API_BASE}/journal/monthly`)
  if (!res.ok) throw new Error(`GET /journal/monthly ${res.status}`)
  return (await res.json()) as JournalMonthly[]
}

export interface ScorePoint {
  country: string
  bucket_start: string
  score_value: number
}

export async function fetchCountryScores(country: string): Promise<ScorePoint[]> {
  const res = await fetch(
    `${API_BASE}/scores?score_name=composite&country=${encodeURIComponent(country)}&limit=200`,
  )
  if (!res.ok) throw new Error(`GET /scores ${res.status}`)
  const rows = (await res.json()) as ScorePoint[]
  return rows.sort((a, b) => a.bucket_start.localeCompare(b.bucket_start))
}

export interface ContestedStory {
  story_id: string
  title: string
  divergence: number
  groups: Record<string, number>
}

export async function fetchContestedStories(): Promise<ContestedStory[]> {
  const res = await fetch(`${API_BASE}/disagreement/top?hours=72&limit=5`)
  if (!res.ok) throw new Error(`GET /disagreement/top ${res.status}`)
  return (await res.json()) as ContestedStory[]
}

export interface CompositeMovers {
  latest_month: string | null
  global_mean: number | null
  movers: { country: string; latest: number; delta: number }[]
}

export async function fetchCompositeMovers(): Promise<CompositeMovers> {
  const res = await fetch(`${API_BASE}/composite/movers?limit=6`)
  if (!res.ok) throw new Error(`GET /composite/movers ${res.status}`)
  return (await res.json()) as CompositeMovers
}

/** GPRGauge pattern from the proto-OSINT project: plain words for a stress level. */
export function stressBand(mean: number | null): {
  word: string
  tone: string
  detail: string
} {
  if (mean === null)
    return {
      word: "no data",
      tone: "text-neutral-500",
      detail: "No composite scores computed yet.",
    }
  if (mean >= 0.7)
    return {
      word: "high stress",
      tone: "text-red-400",
      detail:
        "The average country stress score is far above its usual range — many countries are behaving unusually versus their own history.",
    }
  if (mean >= 0.55)
    return {
      word: "elevated",
      tone: "text-amber-300",
      detail:
        "The average country stress score sits above its usual range — more deviation from normal than a typical month.",
    }
  return {
    word: "calm",
    tone: "text-emerald-300",
    detail:
      "The average country stress score is inside its usual range — most countries look like their own normal.",
  }
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
