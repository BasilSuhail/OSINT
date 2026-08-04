"use client"

import type { ReactNode } from "react"

/** The tag at the right of a row: what kind of thing this is, and whether it
 *  is still growing. Nothing to say → nothing drawn, because an empty box is
 *  worse than no box. */
export function TagChip({
  category,
  escalating,
}: {
  category?: string | null
  escalating?: string | null
}) {
  if (!category) return null
  return (
    <span className="shrink-0 rounded border border-neutral-700 px-1 py-0.5 font-mono text-[9px] uppercase tracking-wide text-neutral-400">
      {category}
      {escalating === "yes" ? " ↑" : ""}
    </span>
  )
}

/** One row in any list of stories (#785).
 *
 *  The console printed the same numbered, time-stamped, tagged list in two
 *  styles — one on the first page, a heavier one in a map selection, with a
 *  severity dot and a `SOURCE · PLACE · KM` line under every headline. That
 *  second line doubled every row for its least valuable content: on a cluster
 *  of GDELT records it repeated the word GDELT down the whole panel, and it
 *  was narrow enough that the distance it existed to show got ellipsised.
 *
 *  This is the first page's row, because that is the one the reader spends
 *  their time in. What a particular list knows and the others do not goes in
 *  `hint` — read on hover, costing no height.
 */
export function ListRow({
  n,
  time,
  timestamp,
  title,
  hint,
  trailing,
  onOpen,
}: {
  n: number
  /** Already formatted: only the caller knows whether the meaningful moment is
   *  when a story was last seen or when an event occurred. */
  time: string
  /** ISO instant behind `time`, when there is one — makes the clock a real
   *  `<time>` element and puts the full date on hover. */
  timestamp?: string
  title: string
  /** Row detail shown on hover rather than printed: source, place, distance. */
  hint?: string
  trailing?: ReactNode
  onOpen: () => void
}) {
  const clockClass =
    "w-9 shrink-0 pt-px text-right font-mono text-[10px] tabular-nums text-neutral-500"
  return (
    <div className="py-0.5">
      <button
        onClick={onOpen}
        title={hint}
        className="flex w-full items-start gap-2 rounded-md px-1 py-0.5 text-left transition-colors hover:bg-neutral-900/30"
      >
        <span className="w-4 shrink-0 pt-px text-right font-mono text-[10px] tabular-nums text-neutral-600">
          {n}
        </span>
        {/* The clock is the flex item itself, whether or not it is a <time> —
            wrapping it would put an unstyled element in the row's gutter. */}
        {timestamp ? (
          <time
            dateTime={timestamp}
            title={new Date(timestamp).toLocaleString()}
            className={clockClass}
          >
            {time}
          </time>
        ) : (
          <span className={clockClass}>{time}</span>
        )}
        <span
          className="min-w-0 flex-1 overflow-hidden text-[11.5px] leading-4 text-neutral-300"
          style={{
            display: "-webkit-box",
            WebkitLineClamp: 3,
            WebkitBoxOrient: "vertical",
          }}
        >
          {title}
        </span>
        {trailing}
      </button>
    </div>
  )
}
