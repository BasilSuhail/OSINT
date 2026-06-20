import { NextResponse } from "next/server"

/**
 * Proxies CelesTrak TLE downloads so the browser doesn't hit a missing
 * Access-Control-Allow-Origin header. Cached for 1h — TLE catalogues only
 * meaningfully change once or twice a day per satellite.
 */
export const revalidate = 3600

const ALLOWED_GROUPS = new Set([
  "stations",
  "active",
  "starlink",
  "gps-ops",
  "weather",
  "noaa",
  "geo",
  "science",
  "visual",
])

export async function GET(request: Request) {
  const url = new URL(request.url)
  const group = url.searchParams.get("group") || "stations"
  if (!ALLOWED_GROUPS.has(group)) {
    return NextResponse.json({ error: "invalid group" }, { status: 400 })
  }

  const upstream = await fetch(
    `https://celestrak.org/NORAD/elements/gp.php?GROUP=${group}&FORMAT=tle`,
    { next: { revalidate: 3600 } },
  )
  if (!upstream.ok) {
    return NextResponse.json({ error: "celestrak upstream failed" }, { status: 502 })
  }
  const text = await upstream.text()
  return new NextResponse(text, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=3600, s-maxage=3600",
    },
  })
}
