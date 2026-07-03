"use client"

import Link from "next/link"
import useSWR from "swr"
import { fetchScoreboard, fetchTopStories } from "@/lib/analytics"

const REFRESH_MS = 60_000

/** Live pulse of the analytical layer, styled like the dataset health chips. */
export function AnalyticsChips() {
  const stories = useSWR("topbar-stories", () => fetchTopStories(24, 500), {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })
  const journal = useSWR("topbar-journal", fetchScoreboard, {
    refreshInterval: 5 * REFRESH_MS,
    revalidateOnFocus: false,
  })

  const storyCount = stories.data?.length
  const multiOutlet = stories.data?.filter((s) => s.outlet_count >= 2).length
  const pending = journal.data?.reduce((sum, line) => sum + line.pending, 0)

  return (
    <>
      <Link
        href="/stories"
        title="story clusters seen in the last 24h (multi-outlet in cyan)"
        className="shrink-0 font-mono text-[8px] uppercase tracking-wide text-neutral-400 hover:text-neutral-200"
      >
        <span className="text-neutral-200/80">stories</span>{" "}
        <span className="text-neutral-500">{storyCount ?? "—"}</span>{" "}
        <span className="text-cyan-400">{multiOutlet ?? "—"}×2+</span>
      </Link>
      <Link
        href="/scoreboard"
        title="forward forecasts awaiting their window to mature"
        className="shrink-0 font-mono text-[8px] uppercase tracking-wide text-neutral-400 hover:text-neutral-200"
      >
        <span className="text-neutral-200/80">forecasts</span>{" "}
        <span className="text-amber-400">{pending ?? "—"} pending</span>
      </Link>
    </>
  )
}
