"use client"

import useSWR from "swr"
import { SystemStatusBar } from "@/components/SystemStatusBar"
import {
  fetchBaselinesReport,
  fetchScoreboard,
  type BaselineResultRow,
} from "@/lib/analytics"

const REFRESH_MS = 5 * 60_000

function fmt(value: number | null, digits = 3): string {
  return value == null ? "—" : value.toFixed(digits)
}

function aurocTone(row: BaselineResultRow): string {
  if (row.auroc == null) return "text-neutral-500"
  if (row.baseline.startsWith("B6")) {
    return row.auroc >= 0.9 ? "text-emerald-300" : row.auroc <= 0.55 ? "text-red-400" : "text-amber-300"
  }
  return "text-neutral-200"
}

const CELL = "px-2 py-1 text-right font-mono text-[11px] tabular-nums"
const HEAD = "px-2 py-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500"

function BaselineTable({ rows }: { rows: BaselineResultRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-neutral-800 text-left">
            <th className={HEAD}>contender</th>
            <th className={`${HEAD} text-right`}>k</th>
            <th className={`${HEAD} text-right`}>n</th>
            <th className={`${HEAD} text-right`}>pos rate</th>
            <th className={`${HEAD} text-right`}>AUROC</th>
            <th className={`${HEAD} text-right`}>AUPR</th>
            <th className={`${HEAD} text-right`}>Brier</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              className={
                row.baseline.startsWith("B6")
                  ? "border-b border-neutral-800/50 bg-neutral-800/30"
                  : "border-b border-neutral-800/50"
              }
            >
              <td className="px-2 py-1 text-[11px] text-neutral-200">{row.baseline}</td>
              <td className={`${CELL} text-neutral-400`}>{row.horizon_months}</td>
              <td className={`${CELL} text-neutral-400`}>{row.n.toLocaleString()}</td>
              <td className={`${CELL} text-neutral-400`}>{fmt(row.positive_rate, 3)}</td>
              <td className={`${CELL} ${aurocTone(row)}`}>{fmt(row.auroc)}</td>
              <td className={`${CELL} text-neutral-300`}>{fmt(row.aupr)}</td>
              <td className={`${CELL} text-neutral-300`}>{fmt(row.brier)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Section({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
      <h2 className="text-sm font-semibold text-neutral-100">{title}</h2>
      <p className="mb-3 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
        {subtitle}
      </p>
      {children}
    </section>
  )
}

export default function ScoreboardPage() {
  const journal = useSWR("journal-scoreboard", fetchScoreboard, {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })
  const baselines = useSWR("baselines-report", fetchBaselinesReport, {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })

  return (
    <div className="flex min-h-screen flex-col bg-neutral-950">
      <SystemStatusBar />
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4">
        <header>
          <h1 className="text-lg font-semibold text-neutral-100">Scoreboard</h1>
          <p className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
            can the composite beat knowing nothing? · pre-registered eval, 2023-24 test window
            untouched
          </p>
        </header>

        <Section
          title="Forward track record"
          subtitle="every forecast server-stamped before the outcome is known · graded once its window matures · hindcasts forbidden"
        >
          {journal.error ? (
            <p className="font-mono text-[11px] text-red-400">journal API unreachable</p>
          ) : !journal.data ? (
            <p className="font-mono text-[11px] text-neutral-500">loading…</p>
          ) : journal.data.length === 0 ? (
            <p className="font-mono text-[11px] text-neutral-500">no forecasts issued yet</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-neutral-800 text-left">
                    <th className={HEAD}>source</th>
                    <th className={`${HEAD} text-right`}>k</th>
                    <th className={`${HEAD} text-right`}>issued</th>
                    <th className={`${HEAD} text-right`}>graded</th>
                    <th className={`${HEAD} text-right`}>pending</th>
                    <th className={`${HEAD} text-right`}>pos rate</th>
                    <th className={`${HEAD} text-right`}>Brier</th>
                  </tr>
                </thead>
                <tbody>
                  {journal.data.map((line, i) => (
                    <tr key={i} className="border-b border-neutral-800/50">
                      <td className="px-2 py-1 text-[11px] text-neutral-200">
                        {line.source} {line.method_version}
                      </td>
                      <td className={`${CELL} text-neutral-400`}>{line.horizon_months}</td>
                      <td className={`${CELL} text-neutral-200`}>{line.issued}</td>
                      <td className={`${CELL} text-emerald-300`}>{line.graded}</td>
                      <td className={`${CELL} text-amber-300`}>{line.pending}</td>
                      <td className={`${CELL} text-neutral-300`}>{fmt(line.positive_rate)}</td>
                      <td className={`${CELL} text-neutral-300`}>{fmt(line.brier)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 font-mono text-[9px] uppercase tracking-wide text-neutral-600">
                pending falls as forecast windows mature — the record is earned, never backfilled
              </p>
            </div>
          )}
        </Section>

        {baselines.error ? (
          <Section title="Baselines" subtitle="latest report from make baselines">
            <p className="font-mono text-[11px] text-red-400">
              no baselines report — run `make baselines`
            </p>
          </Section>
        ) : !baselines.data ? (
          <Section title="Baselines" subtitle="latest report from make baselines">
            <p className="font-mono text-[11px] text-neutral-500">loading…</p>
          </Section>
        ) : (
          <>
            <Section
              title="Head-to-head — composite vs the no-skill trio"
              subtitle={`common support only · eval ${baselines.data.eval_window[0]} → ${baselines.data.eval_window[1]} · generated ${new Date(baselines.data.generated_at).toLocaleString()}`}
            >
              <BaselineTable rows={baselines.data.head_to_head_common_support} />
              <p className="mt-2 text-[11px] leading-relaxed text-neutral-400">
                The composite currently carries market + hazard signals only, scored against
                geopolitical-only labels — the honest reading of a coin-flip AUROC is a domain
                mismatch, not a final verdict. Geopolitical signals (GDELT) and P4/P5 labels are
                the fix.
              </p>
            </Section>
            <Section
              title="Full panel — the bar itself"
              subtitle="B0 random / B1 persistence / B2 base rate on every eval-window row"
            >
              <BaselineTable rows={baselines.data.results} />
            </Section>
          </>
        )}
      </main>
    </div>
  )
}
