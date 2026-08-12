import type { JobRun } from "./analytics"

/** Every job the stack can run. The roster is fixed so the monitor is present
 *  even when everything is idle — a job that has never run is a finding, and a
 *  list built only from returned rows cannot show one. */
export const JOB_ROSTER = [
  "backfill-signals",
  "labels",
  "panel",
  "baselines",
  "coverage",
  "stories",
  "journal",
] as const

/** CLI and beat variants of the same work collapse into one display name. */
const DISPLAY_NAME: Record<string, string> = { "stories-cluster": "stories" }

/** A run whose heartbeat is older than this is claiming to be running and is
 *  not. Ten minutes is longer than any healthy gap between heartbeats. */
const STALL_MS = 10 * 60_000

export type JobState = "failed" | "stalled" | "working" | "idle"

export interface JobStatus {
  name: string
  state: JobState
  /** Short progress or failure line, when the run has one. */
  text: string | null
  /** When the run started, relative to now. */
  age: string
  detail: string
}

export const JOB_STATE_LABEL: Record<JobState, string> = {
  failed: "failed",
  stalled: "stalled",
  working: "working",
  idle: "idle",
}

/** Worst first, matching the source list: what is broken sits at the top. */
export const JOB_STATE_ORDER: JobState[] = ["failed", "stalled", "working", "idle"]

function ago(iso: string, now: number): string {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000))
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.round(minutes / 60)}h ago`
}

export function deriveJobStatuses(runs: JobRun[], now: number): JobStatus[] {
  const newest = new Map<string, JobRun>()
  for (const run of runs) {
    const name = DISPLAY_NAME[run.job] ?? run.job
    const seen = newest.get(name)
    if (!seen || new Date(run.started_at) > new Date(seen.started_at)) newest.set(name, run)
  }

  return JOB_ROSTER.map((name): JobStatus => {
    const run = newest.get(name)
    if (!run) {
      return { name, state: "idle", text: null, age: "—", detail: "never ran in the last 48h" }
    }
    const age = ago(run.started_at, now)
    if (run.status === "running") {
      const stalled = now - new Date(run.heartbeat_at).getTime() > STALL_MS
      return {
        name,
        state: stalled ? "stalled" : "working",
        text: run.progress ?? (stalled ? "no heartbeat" : "working"),
        age,
        detail: stalled
          ? `started ${age}, no heartbeat for over 10 minutes`
          : (run.progress ?? "running"),
      }
    }
    if (run.status === "failed") {
      return {
        name,
        state: "failed",
        text: "failed",
        age,
        detail: run.detail ?? "no detail recorded",
      }
    }
    return {
      name,
      state: "idle",
      text: null,
      age,
      detail: run.progress ?? "completed",
    }
  })
}

export interface JobGroup {
  state: JobState
  label: string
  count: number
  jobs: JobStatus[]
}

export function groupJobs(statuses: JobStatus[]): JobGroup[] {
  return JOB_STATE_ORDER.map((state) => {
    const jobs = statuses.filter((job) => job.state === state)
    return { state, label: JOB_STATE_LABEL[state], count: jobs.length, jobs }
  }).filter((group) => group.count > 0)
}
