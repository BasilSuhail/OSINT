/** Which shape an aircraft gets on the map, read from its type designator.
 *
 * The feed sends an ICAO type designator — C30J, EC45, H47 — and nothing that
 * says what kind of machine it is. The designator scheme carries no class
 * field, so the only honest way to tell a rotorcraft from a jet is to know the
 * designators, which is what the lists below are.
 *
 * Rotorcraft are the list; everything else that sent a designator gets a wing.
 * The recognised-only alternative was tried and drew a screenful of shapeless
 * marks over one country, because a military feed carries hundreds of types
 * and no list of names will ever hold them all. The residual is a wing rather
 * than nothing because the rotorcraft side is matched by whole families as
 * well as by name — an unlisted rotorcraft is usually still caught by its
 * maker's prefix, so what falls through is overwhelmingly fixed wing.
 *
 * `unknown` is kept for the one case it is true of: no designator at all.
 */

export type Silhouette = "fixed-wing" | "rotorcraft" | "unknown"

/** Rotorcraft named one at a time, where the family is mixed or the maker's
 *  prefix is shared with fixed-wing types. Tiltrotors are here: a V-22 spends
 *  the part of a flight worth watching on a map with its rotors up. */
const ROTORCRAFT = new Set([
  // Leonardo / Agusta
  "A109", "A119", "A129", "A139", "A149", "A169", "A189",
  // Airbus, from the Aérospatiale and MBB lines
  "AS32", "AS3B", "AS50", "AS55", "AS65", "ALO2", "ALO3", "LAMA", "GAZL",
  "PUMA", "BK17",
  // Sikorsky
  "S61", "S61R", "S64", "S65C", "S70", "S76", "S92",
  // Bell
  "B06", "B06T", "B47G", "B212", "B214", "B222", "B230", "B407", "B412",
  "B427", "B429", "B430", "B505", "B525",
  // Robinson
  "R22", "R44", "R66",
  // MD Helicopters
  "EXPL", "MD52", "MD60", "HUCO",
  // European and Commonwealth military types
  "NH90", "EH10", "LYNX", "WASP", "SCOU", "TIGR", "W3",
  // Tiltrotor
  "V22", "V280",
])

/** Whole families where every designator is a rotorcraft, matched by prefix so
 *  a model the list has never heard of still gets the right shape. */
const ROTORCRAFT_PREFIXES = [/^H\d/, /^EC\d/, /^MI\d/, /^KA\d/]

/** The exception the H-and-a-digit rule needs. H25B and H25C are Hawker
 *  business jets, not rotorcraft, and they fly in this feed. */
const ROTORCRAFT_PREFIX_EXCEPTIONS = [/^H25/]

/**
 * The shape for a type designator, or `unknown` when the feed sent none.
 *
 * Whitespace and case come off first: the feed sends the designator as it was
 * filed, and a lower-cased one is the same aircraft.
 */
export function aircraftSilhouette(type: string | null | undefined): Silhouette {
  const code = type?.trim().toUpperCase()
  if (!code) return "unknown"
  if (ROTORCRAFT.has(code)) return "rotorcraft"
  if (
    !ROTORCRAFT_PREFIX_EXCEPTIONS.some((rule) => rule.test(code)) &&
    ROTORCRAFT_PREFIXES.some((rule) => rule.test(code))
  ) {
    return "rotorcraft"
  }
  return "fixed-wing"
}
