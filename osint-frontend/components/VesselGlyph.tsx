/** The marks the vessel layer draws (#954).
 *
 * Two shapes, not seven. A hull under way points where the vessel says it is
 * pointing; a hull that is stopped, anchored or moored is a blunt mark that
 * points nowhere. The category is not in the shape and not in the colour:
 * seven silhouettes at map size would be seven smudges, and seven more colours
 * on a map that already spends colour on disasters would be a second legend
 * arguing with the first. What a vessel is, the card says.
 *
 * Both shapes are bow-up in their own box, so a bearing can be applied with no
 * correction afterwards.
 */

/** A hull seen from above: pointed bow, parallel sides, square stern. */
const UNDER_WAY_PATH = "M12 2.2 L16.4 9.4 L16.4 20.4 L7.6 20.4 L7.6 9.4 Z"

/** Stopped: the same hull, shortened and blunted. It is still a vessel, and it
 *  is still where the transponder said, but nothing about it says direction. */
const STOPPED_PATH = "M12 6.6 L15.6 11 L15.6 18 L8.4 18 L8.4 11 Z"

export function VesselGlyph({
  underWay,
  bearing,
  suspect = false,
  className,
}: {
  underWay: boolean
  /** A position the console does not believe. Drawn hollow, because the shape
   *  is still a claim somebody transmitted and the outline is the difference
   *  between reporting it and endorsing it. */
  suspect?: boolean
  /** Degrees from north. Null leaves the mark unrotated: pointing north
   *  because nothing was transmitted would be a direction the vessel never
   *  claimed. */
  bearing: number | null
  className?: string
}) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className={className}
      style={{
        transform: underWay && bearing != null ? `rotate(${bearing}deg)` : undefined,
      }}
    >
      <path
        d={underWay ? UNDER_WAY_PATH : STOPPED_PATH}
        fill={suspect ? "none" : "currentColor"}
        stroke={suspect ? "currentColor" : undefined}
        strokeWidth={suspect ? 2 : undefined}
        strokeDasharray={suspect ? "3 2" : undefined}
        strokeLinejoin="round"
      />
    </svg>
  )
}
