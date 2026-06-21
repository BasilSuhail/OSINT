import { NextResponse } from "next/server"

/**
 * Proxies NASA's NeoWS feed so the API key (or DEMO_KEY default) lives only
 * on the server, never in the browser. Cached 1h — close-approach predictions
 * don't change inside the day, and we only render ~10-50 entries.
 */
export const revalidate = 3600

export async function GET() {
  const today = new Date()
  const end = new Date(today.getTime() + 6 * 24 * 60 * 60 * 1000)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)

  const apiKey = process.env.NASA_API_KEY ?? "DEMO_KEY"
  const url =
    "https://api.nasa.gov/neo/rest/v1/feed" +
    `?start_date=${fmt(today)}` +
    `&end_date=${fmt(end)}` +
    `&api_key=${apiKey}`

  try {
    const upstream = await fetch(url, { next: { revalidate: 3600 } })
    if (!upstream.ok) {
      return NextResponse.json({ error: "neo upstream failed" }, { status: 502 })
    }
    const data = await upstream.json()
    return NextResponse.json(data, {
      headers: { "cache-control": "public, max-age=3600, s-maxage=3600" },
    })
  } catch {
    return NextResponse.json({ error: "neo fetch error" }, { status: 502 })
  }
}
