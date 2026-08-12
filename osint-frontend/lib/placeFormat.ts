/**
 * Reading the city and weather blocks out loud (#932).
 *
 * Separate from the panel because each of these is a small decision about not
 * overstating a number, and a decision worth a test is worth a name.
 */

/** How far the named settlement is from the point that was clicked.
 *
 *  The distance is the reader's way of judging whether the weather above is
 *  about where they clicked or about somewhere down the road, so "here" has to
 *  mean here — under half a kilometre, which is inside most towns' own
 *  coordinate error.
 */
export function distanceLabel(km: number): string {
  if (km < 0.5) return "here"
  if (km < 1) return `${Math.round(km * 1000)} m away`
  if (km < 10) return `${km.toFixed(1)} km away`
  return `${Math.round(km)} km away`
}

/** One decimal. Weather is not measured finer, and showing more implies it is. */
export function temperature(celsius: number | null): string | null {
  if (celsius == null) return null
  return `${celsius.toFixed(1)}°C`
}

const POINTS = [
  "N",
  "NNE",
  "NE",
  "ENE",
  "E",
  "ESE",
  "SE",
  "SSE",
  "S",
  "SSW",
  "SW",
  "WSW",
  "W",
  "WNW",
  "NW",
  "NNW",
] as const

/** The compass point a bearing falls on, to sixteen points. */
export function compass(degrees: number): string {
  const index = Math.round(((degrees % 360) + 360) % 360 / 22.5) % 16
  return POINTS[index]
}

/** Wind as a person says it.
 *
 *  MET reports metres per second and the direction the wind blows *from* —
 *  "from SSW" rather than "SSW", because the other reading is the opposite
 *  wind. Converted to km/h, which is the unit the rest of this screen uses for
 *  distance.
 */
export function windLabel(metresPerSecond: number | null, fromDegrees: number | null): string | null {
  if (metresPerSecond == null) return null
  const kmh = Math.round(metresPerSecond * 3.6)
  if (fromDegrees == null) return `${kmh} km/h`
  return `${kmh} km/h from ${compass(fromDegrees)}`
}

/** What window the high and low cover. Normally a day; smaller at the end of a
 *  forecast, and saying so is the difference between a measurement and a claim.
 */
export function rangeLabel(hours: number): string | null {
  if (hours <= 0) return null
  return `next ${hours} h`
}
