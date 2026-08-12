import { describe, expect, it } from "vitest"

import type { JobRun } from "@/lib/analytics"
import { deriveJobStatuses, groupJobs, JOB_ROSTER } from "@/lib/jobStatus"

const NOW = Date.parse("2026-08-12T12:00:00Z")

function run(overrides: Partial<JobRun> & { job: string }): JobRun {
  return {
    id: 1,
    status: "done",
    started_at: "2026-08-12T11:30:00Z",
    heartbeat_at: "2026-08-12T11:59:00Z",
    finished_at: null,
    progress: null,
    detail: null,
    ...overrides,
  }
}

describe("deriveJobStatuses", () => {
  it("reports every job in the roster, including ones that never ran", () => {
    const statuses = deriveJobStatuses([], NOW)
    expect(statuses.map((s) => s.name)).toEqual([...JOB_ROSTER])
    expect(statuses.every((s) => s.state === "idle")).toBe(true)
    expect(statuses[0].detail).toBe("never ran in the last 48h")
  })

  it("calls a running job with a fresh heartbeat working", () => {
    const [job] = deriveJobStatuses([run({ job: "labels", status: "running" })], NOW).filter(
      (s) => s.name === "labels",
    )
    expect(job.state).toBe("working")
    expect(job.age).toBe("30m ago")
  })

  it("calls a running job with a dead heartbeat stalled", () => {
    const [job] = deriveJobStatuses(
      [run({ job: "labels", status: "running", heartbeat_at: "2026-08-12T11:00:00Z" })],
      NOW,
    ).filter((s) => s.name === "labels")
    expect(job.state).toBe("stalled")
    expect(job.detail).toContain("no heartbeat")
  })

  it("carries the failure reason rather than only the word failed", () => {
    const [job] = deriveJobStatuses(
      [run({ job: "panel", status: "failed", detail: "connection refused" })],
      NOW,
    ).filter((s) => s.name === "panel")
    expect(job.state).toBe("failed")
    expect(job.detail).toBe("connection refused")
  })

  it("collapses the clustering variant into one display name", () => {
    const statuses = deriveJobStatuses([run({ job: "stories-cluster", status: "running" })], NOW)
    const stories = statuses.find((s) => s.name === "stories")
    expect(stories?.state).toBe("working")
    expect(statuses.some((s) => s.name === "stories-cluster")).toBe(false)
  })

  it("keeps only the newest run of a job", () => {
    const statuses = deriveJobStatuses(
      [
        run({ job: "coverage", status: "failed", started_at: "2026-08-12T09:00:00Z" }),
        run({ job: "coverage", status: "running", started_at: "2026-08-12T11:30:00Z" }),
      ],
      NOW,
    )
    expect(statuses.find((s) => s.name === "coverage")?.state).toBe("working")
  })
})

describe("groupJobs", () => {
  it("orders groups worst first and drops empty states", () => {
    const groups = groupJobs(
      deriveJobStatuses(
        [
          run({ job: "panel", status: "failed" }),
          run({ job: "labels", status: "running" }),
        ],
        NOW,
      ),
    )
    expect(groups.map((g) => g.state)).toEqual(["failed", "working", "idle"])
    expect(groups.map((g) => g.count)).toEqual([1, 1, 5])
  })
})
