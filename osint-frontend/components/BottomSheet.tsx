"use client"

/**
 * The phone's panel surface (#942).
 *
 * On a wide screen the deck is a column beside the map. On a phone there is
 * no beside, and the layout that shipped first answered that by covering the
 * map completely whenever a card was open — so reading about a marker meant
 * losing sight of it.
 *
 * A sheet answers it differently: it stands at one of three heights along the
 * bottom edge, and the reader moves it. At rest it is a grip and a title. At
 * half it is a card with the map still above it. At full it is everything
 * except the search bar, which nothing ever covers.
 *
 * The sheet knows nothing about what is inside it. Its only contract is the
 * detent, so the deck goes in unchanged.
 *
 * Dragging is bound to the grip and never to the body. Three gestures already
 * have a claim on a touch inside this rectangle — the map's one-finger pan
 * behind it, the deck's two-finger paging, and a card's own scrolling — and
 * a body drag that tries to defer to all three is the kind of gesture code
 * that works on the phone it was written on.
 */

import { motion } from "framer-motion"
import { useEffect, useRef, useState, type ReactNode } from "react"

import { detentHeights, snapDetent, type Detent } from "@/lib/narrowLayout"
import { useMediaQuery } from "@/lib/useMediaQuery"

const ORDER: Detent[] = ["peek", "half", "full"]

interface BottomSheetProps {
  detent: Detent
  onDetentChange: (detent: Detent) => void
  /** Names what the grip opens, for a reader who cannot see it. */
  label: string
  children: ReactNode
}

/** The viewport height in pixels. `100dvh` is the same number, but a drag has
 *  to compare a finger's travel against it and CSS cannot hand it over.
 *  Zero until mounted, which `detentHeights` is total for. */
function useViewportHeight(): number {
  const [height, setHeight] = useState(0)
  useEffect(() => {
    const read = () => setHeight(window.innerHeight)
    read()
    window.addEventListener("resize", read)
    window.addEventListener("orientationchange", read)
    return () => {
      window.removeEventListener("resize", read)
      window.removeEventListener("orientationchange", read)
    }
  }, [])
  return height
}

export function BottomSheet({ detent, onDetentChange, label, children }: BottomSheetProps) {
  const viewportH = useViewportHeight()
  const heights = detentHeights(viewportH)
  const height = heights[detent]

  //: A reader who has asked their system for less movement gets the heights
  //: without the travel between them. The sheet still moves — it has to, that
  //: is what it is — but it arrives rather than slides.
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)")

  //: A drag ends in a click as well, and cycling on that click would undo
  //: the detent the drag just chose. The tap fallback exists for a reader who
  //: never discovers the drag, so it has to be the tap that did not move.
  const dragged = useRef(false)

  return (
    <motion.div
      className="pointer-events-auto absolute inset-x-0 bottom-0 z-30 flex flex-col overflow-hidden rounded-t-2xl border-t border-white/10 bg-neutral-950/90 shadow-2xl shadow-black/60 backdrop-blur-xl"
      //: Height rather than transform, because the deck inside has to lay out
      //: at the height it ends up with — a scaled or translated sheet shows a
      //: card built for a size it is not.
      animate={{ height }}
      initial={false}
      transition={reduceMotion ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 40 }}
      //: The sheet stands on the bottom edge, and on a phone the bottom edge
      //: is under the home indicator. Padding rather than offset: the sheet
      //: still reaches the edge, its contents stop short of it.
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {/*: The grip is the whole drag surface, and a button as well. Dragging
          is the gesture; tapping is what is left for a reader who was never
          told there is one. */}
      <motion.button
        type="button"
        drag="y"
        dragConstraints={{ top: 0, bottom: 0 }}
        dragElastic={0.6}
        dragMomentum={false}
        onDragStart={() => {
          dragged.current = true
        }}
        onDragEnd={(_, info) => {
          //: Upward travel is negative on screen and positive in sheet height:
          //: dragging up makes the sheet taller. The flip lives here, at the
          //: one place the two coordinate systems meet.
          onDetentChange(snapDetent(height - info.offset.y, viewportH, -info.velocity.y))
        }}
        onClick={() => {
          if (dragged.current) {
            dragged.current = false
            return
          }
          onDetentChange(ORDER[(ORDER.indexOf(detent) + 1) % ORDER.length])
        }}
        aria-label={`${label} — drag or tap to resize`}
        className="flex h-11 w-full shrink-0 cursor-grab touch-none items-center justify-center active:cursor-grabbing"
      >
        <span className="h-1 w-10 rounded-full bg-neutral-700" aria-hidden />
      </motion.button>

      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </motion.div>
  )
}
