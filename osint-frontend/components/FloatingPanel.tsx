"use client"

import { cn } from "@/lib/utils"

/**
 * The shared surface for anything that floats above the map (#503).
 *
 * Owns exactly one concern: what a floating panel looks like. Radius, hairline
 * border, translucent background with backdrop blur, shadow, clipped overflow.
 * The deck, the detail card and any later panel wrap in this, so they cannot
 * drift apart visually — consistent surfaces are what make separate panels read
 * as one product rather than three widgets.
 *
 * It holds no state and knows nothing about its contents.
 */
export function FloatingPanel({
  children,
  className,
  style,
}: {
  children: React.ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <div
      style={style}
      className={cn(
        "overflow-hidden rounded-2xl border border-white/10 bg-neutral-950/85 shadow-2xl shadow-black/60 backdrop-blur-xl",
        className,
      )}
    >
      {children}
    </div>
  )
}
