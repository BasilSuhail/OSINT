"use client"

import useSWR from "swr"
import {
  fetchBaselinesReport,
  fetchScoreboard,
  type BaselineResultRow,
} from "@/lib/analytics"
import { BarRow, Hint, NamedScale } from "./viz"

const REFRESH_MS = 5 * 60_000

function fmt(value: number | null, digits = 3): string {
  return value == null ? "—" : value.toFixed(digits)
}

/** Emphasis form: the composite is the subject (cyan), baselines are context (gray). */
function baselineBar(row: BaselineResultRow): string {
  return row.baseline.startsWith("B6") ? "bg-cyan-400/80" : "bg-neutral-500/60"
}

const CELL = "px-2 py-1 text-right font-mono text-[11px] tabular-nums"
const HEAD = "px-2 py-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500"

const COLUMN_HINTS: Record<string, string> = {
  contender:
    "Who is being graded. B0 predicts randomly, B1 predicts 'same as this month', B2 predicts each country's long-run average, B6 is our composite index. Beating B0–B2 is the minimum bar for claiming any skill.",
  "horizon (months)":
    "How far ahead the forecast looks: will instability occur within the next 1, 3 or 6 months?",
  "sample size":
    "Country-months graded. Bigger sample = more trustworthy numbers.",
  "positive rate":
    "How often the bad outcome actually happened in this sample. The base level every score must be read against.",
  AUROC:
    "Area under the ROC curve: the chance the model ranks a random true-positive above a random true-negative. 0.5 = coin flip (no skill), 1.0 = perfect. Below ~0.55 means indistinguishable from guessing.",
  AUPR:
    "Area under the precision-recall curve — like AUROC but harsher when positives are rare. Compare it to the positive rate: matching it = no skill.",
  Brier:
    "Mean squared error of the probability forecasts. 0 = clairvoyant, 0.25 = coin flip, 1 = perfectly wrong. Lower is better.",
}

function BaselineTable({ rows }: { rows: BaselineResultRow[] }) {
  const headers: { key: string; label: string; align?: string }[] = [
    { key: "contender", label: "contender", align: "text-left" },
    { key: "horizon (months)", label: "horizon (months)" },
    { key: "sample size", label: "sample size" },
    { key: "positive rate", label: "positive rate" },
    { key: "AUROC", label: "AUROC" },
    { key: "AUPR", label: "AUPR" },
    { key: "Brier", label: "Brier" },
  ]
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-neutral-800 text-left">
            {headers.map((h) => (
              <th key={h.key} className={`${HEAD} ${h.align ?? "text-right"}`}>
                <Hint term={h.label} wide>
                  {COLUMN_HINTS[h.key]}
                </Hint>
              </th>
            ))}
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
              <td className={`${CELL} text-neutral-200`}>{fmt(row.auroc)}</td>
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
  subtitle: React.ReactNode
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

/** Forward track record + baselines head-to-head. Deck card / fullscreen body. */
export function ScoreboardPanel() {
  const journal = useSWR("journal-scoreboard", fetchScoreboard, {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })
  const baselines = useSWR("baselines-report", fetchBaselinesReport, {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })

  const gradedLines = (journal.data ?? []).filter((l) => l.brier != null)
  const headToHeadK1 = (baselines.data?.head_to_head_common_support ?? []).filter(
    (r) => r.horizon_months === 1,
  )

  return (
    <div className="flex flex-col gap-4">
      <p className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
        is any of this predictive? graded in public, negatives published — hover anything dotted
      </p>

      <Section
        title="Forward track record"
        subtitle="every forecast is server-stamped before the outcome is knowable, graded exactly once when reality catches up — backfilling is impossible by construction"
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
                  <th className={HEAD}>
                    <Hint term="instrument" wide>
                      Which forecaster made the prediction: the composite stress index, or the
                      disagreement signal (do countries telling the same story very differently
                      predict trouble?). Each is graded separately.
                    </Hint>
                  </th>
                  <th className={`${HEAD} text-right`}>
                    <Hint term="horizon (months)" wide>
                      {COLUMN_HINTS["horizon (months)"]}
                    </Hint>
                  </th>
                  <th className={`${HEAD} text-right`}>
                    <Hint term="issued" wide>
                      Forecasts made so far — written down before the outcome was knowable.
                    </Hint>
                  </th>
                  <th className={`${HEAD} text-right`}>
                    <Hint term="graded" wide>
                      Forecasts whose window has fully passed, marked right or wrong against
                      ground-truth conflict data. Green because these are the earned record.
                    </Hint>
                  </th>
                  <th className={`${HEAD} text-right`}>
                    <Hint term="awaiting grade" wide>
                      Forecasts whose window has not closed yet. Amber = still on the clock;
                      this number falls as months mature.
                    </Hint>
                  </th>
                  <th className={`${HEAD} text-right`}>
                    <Hint term="positive rate" wide>
                      {COLUMN_HINTS["positive rate"]}
                    </Hint>
                  </th>
                  <th className={`${HEAD} text-right`}>
                    <Hint term="Brier score" wide>
                      {COLUMN_HINTS.Brier} This single number is the difference between a
                      forecasting system and a mood ring.
                    </Hint>
                  </th>
                </tr>
              </thead>
              <tbody>
                {journal.data.map((line, i) => (
                  <tr key={i} className="border-b border-neutral-800/50">
                    <td className="px-2 py-1 text-[11px] text-neutral-200">
                      {line.source}{" "}
                      <span className="text-neutral-500">{line.method_version}</span>
                    </td>
                    <td className={`${CELL} text-neutral-400`}>{line.horizon_months}</td>
                    <td className={`${CELL} text-neutral-200`}>{line.issued}</td>
                    <td className={`${CELL} text-emerald-300`}>{line.graded} ✓</td>
                    <td className={`${CELL} text-amber-300`}>{line.pending} ⏳</td>
                    <td className={`${CELL} text-neutral-300`}>{fmt(line.positive_rate)}</td>
                    <td className={`${CELL} text-neutral-300`}>{fmt(line.brier)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className="mt-3 mb-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
              <Hint term="the Brier scale — where each instrument lands once graded" wide>
                0 means clairvoyant, 0.25 is what a coin flip earns, 1 is perfectly wrong. An
                instrument worth selling sinks below 0.25 and stays there. Markers appear as
                soon as the first forecasts are graded.
              </Hint>
            </p>
            <NamedScale
              goodSide="left"
              references={[
                { at: 0, label: "clairvoyant" },
                { at: 0.25, label: "coin flip" },
                { at: 1, label: "perfectly wrong" },
              ]}
              markers={gradedLines.map((l) => ({
                at: l.brier as number,
                label: `${l.source} k=${l.horizon_months}`,
                tone: l.source === "composite" ? "bg-cyan-400" : "bg-emerald-400",
              }))}
            />
            {gradedLines.length === 0 ? (
              <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-600">
                no forecasts graded yet — markers land here as windows mature. the record is
                earned, never backfilled
              </p>
            ) : null}
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
            title="Head-to-head — the composite vs deliberately dumb rivals"
            subtitle={`same rows for every contender · evaluation ${baselines.data.eval_window[0]} → ${baselines.data.eval_window[1]} · 2023–24 kept untouched for the final test`}
          >
            <p className="mb-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
              <Hint term="AUROC at the 1-month horizon — the vertical line is a coin flip" wide>
                Each bar is one contender&apos;s AUROC predicting next month. 0.5 = guessing.
                The composite (cyan) must beat the gray bars before any predictive claim is
                honest — right now it does not, and that is published on purpose.
              </Hint>
            </p>
            <div>
              <BarRow
                label="← coin flip reference"
                value="0.500"
                fraction={0.5}
                barClass="bg-transparent border-r-2 border-dashed border-neutral-500"
                hint="AUROC 0.5 is pure guessing. Any bar that does not clearly pass this mark has no predictive skill, whatever it is called."
              />
              {headToHeadK1.map((row) => (
                <BarRow
                  key={row.baseline}
                  label={row.baseline}
                  value={fmt(row.auroc)}
                  fraction={row.auroc ?? 0}
                  barClass={baselineBar(row)}
                  emphasis={row.baseline.startsWith("B6")}
                  hint={COLUMN_HINTS.contender}
                />
              ))}
            </div>
            <div className="mt-3">
              <BaselineTable rows={baselines.data.head_to_head_common_support} />
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-neutral-400">
              Plain reading: with all three signal domains live, the composite scores a coin
              flip — on this exam <i>and</i> on the pre-registered onset exam (calm countries
              only). Both negatives are published; the per-indicator decomposition
              (`make indicator-ranking`) shows the recoverable signal lives in the{" "}
              <i>magnitude</i> of deviations, which the next composite version must not
              discard. Publishing the losses is what makes the rest of this dashboard
              believable.
            </p>
          </Section>
          <Section
            title="Full panel — the bar itself"
            subtitle="the dumb rivals on every evaluation row: this is the score any real instrument has to beat"
          >
            <BaselineTable rows={baselines.data.results} />
          </Section>
        </>
      )}
    </div>
  )
}
