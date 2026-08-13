import type { Silhouette } from "@/lib/aircraftSilhouette"

/** The marks the live aircraft layer draws, one per airframe class (#952).
 *
 * Drawn here rather than pulled from an icon set because the map needs three
 * shapes that read against each other at a size a cursor can barely hit — a
 * wing, a rotor, and a mark that claims neither — and an icon set gives you
 * whatever its author happened to draw.
 *
 * Every shape is nose-up in its own box, so `rotate(track)` is the course the
 * transponder reported with nothing to correct for afterwards. The glyph the
 * layer replaced was a right-pointing Unicode arrow rotated the same way,
 * which put every aircraft on the map ninety degrees off its own heading.
 */

/** Swept wing, tailplane, pointed nose: an aircraft from above, which is the
 *  only view a map has. */
const FIXED_WING_PATH =
  "M12 1.2 L12.9 4.6 L13.1 9 L22.4 14.6 L22.4 15.9 L13.4 13 L12.8 17.4 " +
  "L12.6 18.2 L16.4 21.2 L16.4 22.2 L12 20.6 L7.6 22.2 L7.6 21.2 L11.4 18.2 " +
  "L11.2 17.4 L10.6 13 L1.6 15.9 L1.6 14.6 L10.9 9 L11.1 4.6 Z"

/** Cabin narrowing into a tail boom. Kept narrow so the blades clear it: the
 *  blades are the only part of this shape a wing does not also have. */
const ROTORCRAFT_BODY_PATH =
  "M12 3.4 C13.9 3.4 15.2 5.6 15.2 8.4 C15.2 10.8 14.4 12.7 13.2 13.6 " +
  "L12.9 20 L11.1 20 L10.8 13.6 C9.6 12.7 8.8 10.8 8.8 8.4 C8.8 5.6 10.1 3.4 12 3.4 Z"

/** Blades, crossed, drawn over the cabin rather than behind it: behind, the
 *  body eats the middle of both and four stubs are left. They run the full
 *  width of the box and are the heaviest strokes in it, because at the size
 *  this is drawn on a map they are the whole difference between the two
 *  aircraft shapes. */
const ROTORCRAFT_BLADES_PATH = "M1.6 2.6 L22.4 14.2 M22.4 2.6 L1.6 14.2"

/** A delta with a notched tail. It points, so the course still shows, but it
 *  has neither wing nor rotor because the type designator did not say. */
const UNKNOWN_PATH = "M12 2.6 L19 20.4 L12 16.4 L5 20.4 Z"

export function AircraftGlyph({
  silhouette,
  track,
  color,
  className,
}: {
  silhouette: Silhouette
  /** Course over the ground, degrees from north. Null leaves the mark
   *  unrotated: pointing north because nothing was reported would be a
   *  direction the aircraft never claimed. */
  track: number | null
  /** The mark's colour, as a value rather than a class: the rail prints the
   *  same constant beside the switch, and a legend that keeps its own copy of
   *  a colour is a legend that will eventually be wrong. The element owns its
   *  `style` for the rotation, so this cannot be passed in as one. */
  color?: string
  className?: string
}) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className={className}
      style={{
        color,
        transform: track != null ? `rotate(${track}deg)` : undefined,
      }}
    >
      {silhouette === "rotorcraft" ? (
        <>
          <path d={ROTORCRAFT_BODY_PATH} fill="currentColor" />
          {/* Horizontal stabiliser and tail rotor: small, but they are what
              stops the boom reading as a stalk. */}
          <rect x="9.2" y="19.5" width="5.6" height="1.2" rx="0.6" fill="currentColor" />
          <ellipse cx="15.1" cy="20.1" rx="0.9" ry="1.6" fill="currentColor" />
          <path
            d={ROTORCRAFT_BLADES_PATH}
            stroke="currentColor"
            strokeOpacity="0.9"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </>
      ) : (
        <path
          d={silhouette === "fixed-wing" ? FIXED_WING_PATH : UNKNOWN_PATH}
          fill="currentColor"
        />
      )}
    </svg>
  )
}
