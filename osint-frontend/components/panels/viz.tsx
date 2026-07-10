"use client"

/**
 * Shared teaching-grade viz primitives for the analytical cards (#392, #394).
 *
 * Design rules (dataviz method): colour is assigned by job — sequential cyan
 * for magnitude, reserved status colours (emerald good / amber warn / red bad)
 * never reused as series colours, text always in text tokens with a coloured
 * mark *beside* it, reference lines named in words, every number hoverable.
 *
 * Tooltips render through a document.body portal at position:fixed and clamp
 * to the viewport (#394): they can never inflate a scroll container's width
 * (the table-jitter bug), be clipped by overflow, or sit behind a sibling
 * card. Flips above the anchor when there is no room below.
 */

import { useCallback, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"

const TIP_WIDTH = 288 // w-72
const MARGIN = 8

interface TipState {
  x: number
  y: number
  above: boolean
}

function useTip() {
  const [tip, setTip] = useState<TipState | null>(null)
  const anchor = useRef<HTMLElement | null>(null)

  const show = useCallback((el: HTMLElement) => {
    anchor.current = el
    const rect = el.getBoundingClientRect()
    const x = Math.min(
      Math.max(rect.left + rect.width / 2 - TIP_WIDTH / 2, MARGIN),
      window.innerWidth - TIP_WIDTH - MARGIN,
    )
    // Flip above when the lower half of the viewport is crowded.
    const above = rect.bottom > window.innerHeight - 180
    setTip({ x, y: above ? rect.top - MARGIN : rect.bottom + MARGIN, above })
  }, [])

  const hide = useCallback(() => setTip(null), [])
  return { tip, show, hide }
}

function TipBox({ tip, children }: { tip: TipState; children: ReactNode }) {
  if (typeof document === "undefined") return null
  return createPortal(
    <div
      className="pointer-events-none fixed z-[9999] rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 font-sans text-[11px] font-normal normal-case leading-relaxed tracking-normal text-neutral-300 shadow-2xl"
      style={{
        left: tip.x,
        top: tip.above ? undefined : tip.y,
        bottom: tip.above ? window.innerHeight - tip.y : undefined,
        width: TIP_WIDTH,
      }}
    >
      {children}
    </div>,
    document.body,
  )
}

/** Wraps any element; hovering it shows a viewport-clamped explainer. */
export function Tip({
  content,
  children,
  className = "",
}: {
  content: ReactNode
  children: ReactNode
  className?: string
}) {
  const { tip, show, hide } = useTip()
  return (
    <span
      className={`cursor-help ${className}`}
      onMouseEnter={(e) => show(e.currentTarget)}
      onMouseLeave={hide}
      onFocus={(e) => show(e.currentTarget)}
      onBlur={hide}
    >
      {children}
      {tip ? <TipBox tip={tip}>{content}</TipBox> : null}
    </span>
  )
}

/** Dotted-underline hover explainer. Everything numeric on the cards wears one. */
export function Hint({ term, children }: { term: ReactNode; children: ReactNode }) {
  return (
    <Tip content={children}>
      <span className="border-b border-dotted border-neutral-600">{term}</span>
    </Tip>
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
    <div className="min-w-0 rounded-xl border border-neutral-800 bg-neutral-900/50 px-3 py-2">
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
    <div className="flex w-full items-center gap-2 py-0.5">
      <span
        className={`w-24 shrink-0 truncate text-right font-mono text-[10px] sm:w-36 ${
          emphasis ? "text-neutral-100" : "text-neutral-400"
        }`}
      >
        {label}
      </span>
      <span className="relative h-3.5 min-w-0 flex-1 overflow-hidden rounded-sm bg-neutral-800/40">
        <span
          className={`absolute inset-y-0 left-0 rounded-r-[3px] ${barClass}`}
          style={{ width }}
        />
      </span>
      <span className="w-12 shrink-0 font-mono text-[10px] tabular-nums text-neutral-300">
        {value}
      </span>
    </div>
  )
  return hint ? (
    <Tip content={hint} className="block">
      {row}
    </Tip>
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
    <div className="px-2 pb-6 pt-1">
      <div className="mb-1 flex justify-between font-mono text-[9px] uppercase tracking-wide text-neutral-600">
        <span>{goodSide === "left" ? "◀ better" : ""}</span>
        <span>{goodSide === "right" ? "better ▶" : ""}</span>
      </div>
      <div className="relative h-2 rounded-full bg-gradient-to-r from-neutral-700 to-neutral-800">
        {references.map((ref) => (
          <span
            key={ref.label}
            className="absolute -top-0.5 h-3 w-px bg-neutral-500"
            style={{ left: pos(ref.at) }}
          >
            <span className="absolute left-1/2 top-3.5 -translate-x-1/2 whitespace-nowrap font-mono text-[8px] uppercase tracking-wide text-neutral-500">
              {ref.label}
            </span>
          </span>
        ))}
        {markers.map((m) => (
          <span key={m.label} className="absolute -top-1 z-10" style={{ left: pos(m.at) }}>
            <Tip content={`${m.label}: ${m.at.toFixed(3)}`}>
              <span
                className={`block h-4 w-4 -translate-x-1/2 rounded-full border-2 border-neutral-950 ${m.tone}`}
              />
            </Tip>
          </span>
        ))}
      </div>
    </div>
  )
}
