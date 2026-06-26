"use client"

import type { ReactNode } from "react"
import { AnimatePresence, motion } from "framer-motion"

/** A floating detail/overview panel centred on the split separator.
 *
 *  Detail cards used to render as map popups anchored to the marker, covering
 *  half the map (and the footprint you were trying to read). Instead, all
 *  overviews surface here — centred on the divider between the two panes and
 *  following it as you drag (#207). The panel itself is interactive but does not
 *  cover the panes, so map + globe stay fully live behind it (no dimming). */
export function DetailOverlay({
  open,
  leftPct,
  children,
}: {
  open: boolean
  /** Horizontal position of the separator, as a percentage of the viewport. */
  leftPct: number
  children: ReactNode
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 10 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          className="pointer-events-none absolute top-1/2 z-50 -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${leftPct}%` }}
        >
          {/* Re-enable pointer events on the card only, so the panes behind the
              empty margin stay interactive. */}
          <div className="pointer-events-auto">{children}</div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
