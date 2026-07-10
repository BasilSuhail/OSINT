"use client"

/**
 * Shared teaching-grade viz primitives for the analytical cards (#392).
 *
 * Design rules (dataviz method): colour is assigned by job — sequential cyan
 * for magnitude, reserved status colours (emerald good / amber warn / red bad)
 * never reused as series colours, text always in text tokens with a coloured
 * mark *beside* it, reference lines named in words, every number hoverable.
 */

import { type ReactNode } from "react"

/** Dotted-underline hover explainer. Everything numeric on the cards wears one. */
export function Hint({
  term,
  children,
  wide = false,
}: {
  term: ReactNode
  children: ReactNode
  wide?: boolean
}) {
  return (
    <span className="group/hint relative inline-block cursor-help">
      <span className="border-b border-dotted border-neutral-600">{term}</span>
      <span
        className={`pointer-events-none invisible absolute left-1/2 top-full z-50 mt-1.5 -translate-x-1/2 rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-left font-sans text-[11px] font-normal normal-case leading-relaxed tracking-normal text-neutral-300 opacity-0 shadow-xl transition-opacity duration-100 group-hover/hint:visible group-hover/hint:opacity-100 ${
          wide ? "w-72" : "w-56"
        }`}
      >
        {children}
      </span>
    </span>
  )
}

/** KPI stat tile: big number, plain-language label, hover explainer. */
export function StatTile({
  value,
  label,
  hint,
  tone = "text-neutral-200",
}: {
  value: ReactNode
  label: string
  hint: ReactNode
  tone?: string
}) {
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 px-4 py-2">
      <p className={`font-mono text-lg tabular-nums ${tone}`}>{value}</p>
      <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
        <Hint term={label}>{hint}</Hint>
      </p>
    </div>
  )
}

/**
 * Horizontal bar row — the workhorse magnitude chart. Thin mark, direct label,
 * value in a text token, colour carries magnitude or emphasis only.
 */
export function BarRow({
  label,
  value,
  fraction,
  barClass = "bg-cyan-400/80",
  hint,
  emphasis = false,
}: {
  label: ReactNode
  value: string
  fraction: number
  barClass?: string
  hint?: ReactNode
  emphasis?: boolean
}) {
  const width = `${Math.max(0.5, Math.min(1, fraction) * 100)}%`
  const row = (
    <div className="flex items-center gap-2 py-0.5">
      <span
        className={`w-40 shrink-0 truncate text-right font-mono text-[10px] ${
          emphasis ? "text-neutral-100" : "text-neutral-400"
        }`}
      >
        {label}
      </span>
      <span className="relative h-3.5 flex-1 overflow-hidden rounded-sm bg-neutral-800/40">
        <span
          className={`absolute inset-y-0 left-0 rounded-r-[3px] ${barClass}`}
          style={{ width }}
        />
      </span>
      <span className="w-14 shrink-0 font-mono text-[10px] tabular-nums text-neutral-300">
        {value}
      </span>
    </div>
  )
  return hint ? (
    <div className="group/hint relative cursor-help">
      {row}
      <span className="pointer-events-none invisible absolute left-44 top-full z-50 mt-0.5 w-64 rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 font-sans text-[11px] leading-relaxed text-neutral-300 opacity-0 shadow-xl transition-opacity duration-100 group-hover/hint:visible group-hover/hint:opacity-100">
        {hint}
      </span>
    </div>
  ) : (
    row
  )
}

/**
 * A 0→1 scale with named reference points and dot markers — used for Brier
 * (0 clairvoyant · 0.25 coin flip · 1 perfectly wrong) and AUROC-style scores.
 */
export function NamedScale({
  min = 0,
  max = 1,
  references,
  markers,
  goodSide,
}: {
  min?: number
  max?: number
  references: { at: number; label: string }[]
  markers: { at: number; label: string; tone: string }[]
  goodSide: "left" | "right"
}) {
  const pos = (v: number) => `${((v - min) / (max - min)) * 100}%`
  return (
    <div className="px-2 pb-5 pt-1">
      <div className="mb-1 flex justify-between font-mono text-[9px] uppercase tracking-wide text-neutral-600">
        <span>{goodSide === "left" ? "◀ better" : ""}</span>
        <span>{goodSide === "right" ? "better ▶" : ""}</span>
      </div>
      <div className="relative h-2 rounded-full bg-gradient-to-r from-neutral-700 to-neutral-800">
        {references.map((ref) => (
          <span key={ref.label} className="absolute -top-0.5 h-3 w-px bg-neutral-500" style={{ left: pos(ref.at) }}>
            <span className="absolute left-1/2 top-3.5 -translate-x-1/2 whitespace-nowrap font-mono text-[8px] uppercase tracking-wide text-neutral-500">
              {ref.label}
            </span>
          </span>
        ))}
        {markers.map((m) => (
          <span key={m.label} className="group/hint absolute -top-1 z-10 cursor-help" style={{ left: pos(m.at) }}>
            <span className={`block h-4 w-4 -translate-x-1/2 rounded-full border-2 border-neutral-950 ${m.tone}`} />
            <span className="pointer-events-none invisible absolute left-1/2 top-5 z-50 -translate-x-1/2 whitespace-nowrap rounded-lg border border-neutral-700 bg-neutral-950 px-2 py-1 font-mono text-[10px] text-neutral-200 opacity-0 shadow-xl group-hover/hint:visible group-hover/hint:opacity-100">
              {m.label}: {m.at.toFixed(3)}
            </span>
          </span>
        ))}
      </div>
    </div>
  )
}
