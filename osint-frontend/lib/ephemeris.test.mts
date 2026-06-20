/**
 * Ground-truth ephemeris tests. Pin the computed sub-solar point at known
 * astronomical instants (solstices, equinox) against textbook values and
 * fail if the deviation exceeds 0.1°.
 *
 * Run with:  node --test --experimental-strip-types lib/ephemeris.test.mts
 *
 * If the tooling changes (Vitest later), the test bodies port verbatim.
 */

import { strict as assert } from "node:assert"
import { test } from "node:test"
import { computeEphemeris } from "./ephemeris.ts"

const DEG_TOL = 0.1

test("summer solstice 2026-06-21 12:00 UTC → sub-solar lat ≈ 23.44°", () => {
  const eph = computeEphemeris(new Date("2026-06-21T12:00:00Z"))
  assert.ok(Math.abs(eph.sun.lat - 23.44) < DEG_TOL, `sun.lat=${eph.sun.lat}`)
  // Noon at Greenwich on solstice — sub-solar lon should land within ~1° of 0°.
  assert.ok(Math.abs(eph.sun.lon) < 1, `sun.lon=${eph.sun.lon}`)
})

test("winter solstice 2026-12-21 12:00 UTC → sub-solar lat ≈ -23.44°", () => {
  const eph = computeEphemeris(new Date("2026-12-21T12:00:00Z"))
  assert.ok(Math.abs(eph.sun.lat + 23.44) < DEG_TOL, `sun.lat=${eph.sun.lat}`)
})

test("spring equinox 2026-03-20 16:46 UTC → sub-solar lat ≈ 0°", () => {
  const eph = computeEphemeris(new Date("2026-03-20T16:46:00Z"))
  assert.ok(Math.abs(eph.sun.lat) < DEG_TOL, `sun.lat=${eph.sun.lat}`)
})

test("autumn equinox 2026-09-23 06:05 UTC → sub-solar lat ≈ 0°", () => {
  const eph = computeEphemeris(new Date("2026-09-23T06:05:00Z"))
  assert.ok(Math.abs(eph.sun.lat) < DEG_TOL, `sun.lat=${eph.sun.lat}`)
})

test("sub-solar lon advances ~360° / 24h with UTC clock", () => {
  const t0 = new Date("2026-06-21T00:00:00Z")
  const t6 = new Date("2026-06-21T06:00:00Z")
  const eph0 = computeEphemeris(t0)
  const eph6 = computeEphemeris(t6)
  let drift = eph0.sun.lon - eph6.sun.lon
  while (drift > 180) drift -= 360
  while (drift < -180) drift += 360
  // 6h × 15°/h = 90°; allow ±1° for solar declination wobble.
  assert.ok(Math.abs(drift - 90) < 1, `6h sub-solar drift=${drift}°, expected ~90°`)
})

test("moon phase angle wraps within [0, 360)", () => {
  const eph = computeEphemeris(new Date())
  assert.ok(eph.moon.phaseAngle >= 0 && eph.moon.phaseAngle < 360)
})

test("moon illumination in [0, 1]", () => {
  const eph = computeEphemeris(new Date())
  assert.ok(eph.moon.illumination >= 0 && eph.moon.illumination <= 1)
})
