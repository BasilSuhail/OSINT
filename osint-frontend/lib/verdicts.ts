/**
 * Plain-English verdict layer (#403) — deterministic template sentences over
 * measured numbers. No AI anywhere in this file: every phrase is a mechanical
 * map from a number range to words, so the no-hallucination guarantee holds
 * and the same number always reads the same way, dashboard and newsletter
 * alike. Thresholds mirror the corroboration tiers and Brier anchors the
 * cards already teach.
 */

import { countryName } from "./countryName"

export function storyVerdict(story: {
  owner_count: number
  corroboration: number | null
  confirmed: string[]
}): string {
  const score = story.corroboration ?? 0
  const owners = story.owner_count
  if (score >= 0.75 && story.confirmed.length > 0) {
    return (
      `As close to verified as news gets: ${owners} independent organisations ` +
      `and a physical sensor agree.`
    )
  }
  if (score >= 0.75) {
    return `Strongly corroborated — ${owners} independent organisations tell this story.`
  }
  if (score >= 0.5) {
    return `Probably real — ${owners} independent organisations tell this story.`
  }
  if (score > 0) {
    return `A second organisation confirms this — worth a look, not yet solid.`
  }
  return `Only one organisation has said this — treat it as a rumour until someone else confirms.`
}

export function contestedVerdict(item: {
  divergence: number
  groups: Record<string, number>
}): string {
  const blocs = Object.entries(item.groups)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([code]) => countryName(code))
  const pair = blocs.length === 2 ? `${blocs[0]} and ${blocs[1]}` : (blocs[0] ?? "Outlets")
  const strength = item.divergence >= 0.7 ? "very differently" : "somewhat differently"
  return (
    `${pair} are telling this story ${strength} — contested narratives are ` +
    `worth watching; they sometimes precede contested situations.`
  )
}

export function scoreboardVerdict(graded: number, brier: number | null): string {
  if (graded === 0 || brier === null) {
    return (
      "No forecasts graded yet — the track record is still being earned, " +
      "and it can never be backfilled."
    )
  }
  if (brier >= 0.2) {
    return (
      `Across ${graded} graded forecasts the instruments are currently ` +
      `indistinguishable from guessing — published because honesty is the product.`
    )
  }
  return (
    `Across ${graded} graded forecasts the record stands at Brier ${brier.toFixed(3)} — ` +
    `measurably better than guessing (0.250 is a coin flip).`
  )
}
