import type { IngestHealthRow, SourceCoverageRow } from "./types"

export const SOURCE_CADENCE_MIN: Record<string, number> = {
  yfinance: 5,
  fred: 24 * 60,
  gdelt: 15,
  "usgs-quake": 15,
  usgs: 15,
  gdacs: 15,
  "nasa-firms": 60,
  eonet: 30,
  "rss-bbc-world": 60,
  "rss-bbc-uk": 60,
  "rss-reuters-world": 60,
  "rss-dawn": 60,
  "rss-guardian-world": 60,
  "rss-geo-english": 60,
  "rss-aljazeera": 60,
  "rss-cnn-world": 60,
  "rss-nyt-world": 60,
  "rss-france24-en": 60,
  "rss-dw-world": 60,
  "rss-nhk-world": 60,
  "rss-rt-news": 60,
  "rss-tass-en": 60,
  "rss-times-of-india": 60,
  "rss-the-hindu": 60,
  "rss-tribune-pk": 60,
  "rss-cbc-world": 60,
  "rss-abc-au-world": 60,
  "rss-rnz-world": 60,
  "rss-straits-times-world": 60,
  "rss-jpost-world": 60,
  "rss-haaretz-en": 60,
  "rss-arab-news": 60,
  "rss-kyiv-independent": 60,
  "uk-police": 24 * 60,
  acled: 60,
  emdat: 24 * 60,
  "opensky-adsb": 2,
  "abuse-ch-urlhaus": 15,
  "abuse-ch-feodo": 15,
  polymarket: 30,
}

export type HealthBand = "ok" | "warn" | "stale" | "offline"

export interface DatasetHealthSummary {
  key: string
  label: string
  healthy: number
  total: number
  warn: number
  stale: number
  offline: number
  status: HealthBand
  detail: string
  latestIso: string | null
}

interface GroupDef {
  key: string
  label: string
  sources: string[]
}

const GROUPS: GroupDef[] = [
  { key: "acled", label: "ACLED", sources: ["acled"] },
  { key: "gdelt", label: "GDELT", sources: ["gdelt"] },
  { key: "emdat", label: "EM-DAT", sources: ["emdat"] },
  { key: "usgs", label: "USGS", sources: ["usgs-quake", "usgs"] },
  { key: "gdacs", label: "GDACS", sources: ["gdacs"] },
  { key: "firms", label: "FIRMS", sources: ["nasa-firms"] },
  { key: "fred", label: "FRED", sources: ["fred"] },
  { key: "yfinance", label: "yfinance", sources: ["yfinance"] },
  { key: "news", label: "News", sources: Object.keys(SOURCE_CADENCE_MIN).filter((s) =>
    s.startsWith("rss-"),
  ) },
  { key: "opensky", label: "OpenSky", sources: ["opensky-adsb"] },
  { key: "abuse-ch", label: "abuse.ch", sources: ["abuse-ch-urlhaus", "abuse-ch-feodo"] },
  { key: "eonet", label: "EONET", sources: ["eonet"] },
  { key: "polymarket", label: "Polymarket", sources: ["polymarket"] },
]

export function sourceLabel(source: string): string {
  if (source === "acled") return "ACLED"
  if (source === "gdelt") return "GDELT"
  if (source === "emdat") return "EM-DAT"
  if (source === "usgs-quake" || source === "usgs") return "USGS"
  if (source === "gdacs") return "GDACS"
  if (source === "nasa-firms") return "FIRMS"
  if (source === "fred") return "FRED"
  if (source === "yfinance") return "yfinance"
  if (source.startsWith("rss-")) return "News"
  if (source === "opensky-adsb") return "OpenSky"
  if (source.startsWith("abuse-ch-")) return "abuse.ch"
  if (source === "eonet") return "EONET"
  if (source === "polymarket") return "Polymarket"
  return source
}

function latestTimestamp(
  ingest: IngestHealthRow | undefined,
  coverage: SourceCoverageRow | undefined,
): string | null {
  return ingest?.last_success ?? coverage?.latest_fetched_at ?? coverage?.latest_occurred_at ?? null
}

function statusForSource(
  source: string,
  ingest: IngestHealthRow | undefined,
  coverage: SourceCoverageRow | undefined,
  nowMs: number,
): DatasetHealthSummary {
  const cadenceMin = SOURCE_CADENCE_MIN[source] ?? null
  const latestIso = latestTimestamp(ingest, coverage)
  const ageMin =
    latestIso != null ? (nowMs - new Date(latestIso).getTime()) / 60_000 : null

  let status: HealthBand = "offline"
  if (latestIso != null && Number.isFinite(ageMin ?? NaN)) {
    if (cadenceMin == null) {
      status = ageMin != null && ageMin <= 24 * 60 ? "ok" : ageMin != null && ageMin <= 3 * 24 * 60 ? "warn" : "stale"
    } else if (ageMin != null && ageMin <= cadenceMin * 1.5) {
      status = "ok"
    } else if (ageMin != null && ageMin <= cadenceMin * 3) {
      status = "warn"
    } else {
      status = "stale"
    }
  }

  const healthy = status === "ok" ? 1 : 0
  const warn = status === "warn" ? 1 : 0
  const stale = status === "stale" ? 1 : 0
  const offline = status === "offline" ? 1 : 0
  const detail = [
    latestIso ? `last ${latestIso}` : "no signal",
    ingest?.success_n != null ? `success ${ingest.success_n}` : null,
    ingest?.failure_n != null ? `fail ${ingest.failure_n}` : null,
    coverage?.total != null ? `rows ${coverage.total}` : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return {
    key: source,
    label: sourceLabel(source),
    healthy,
    total: 1,
    warn,
    stale,
    offline,
    status,
    detail,
    latestIso,
  }
}

export function summarizeSystemHealth(
  ingestRows: IngestHealthRow[],
  coverageRows: SourceCoverageRow[],
  nowMs = Date.now(),
): DatasetHealthSummary[] {
  const ingestLatest = new Map<string, IngestHealthRow>()
  for (const row of ingestRows) {
    const existing = ingestLatest.get(row.source)
    if (!existing) {
      ingestLatest.set(row.source, row)
      continue
    }
    const a = new Date(row.last_success ?? row.day).getTime()
    const b = new Date(existing.last_success ?? existing.day).getTime()
    if (a > b) ingestLatest.set(row.source, row)
  }

  const coverageLatest = new Map<string, SourceCoverageRow>()
  for (const row of coverageRows) {
    const existing = coverageLatest.get(row.source)
    if (!existing) {
      coverageLatest.set(row.source, row)
      continue
    }
    const a = new Date(row.latest_fetched_at ?? row.latest_occurred_at ?? 0).getTime()
    const b = new Date(existing.latest_fetched_at ?? existing.latest_occurred_at ?? 0).getTime()
    if (a > b) coverageLatest.set(row.source, row)
  }

  return GROUPS.map((group) => {
    const sources = group.sources
    const sourceSummaries = sources.map((source) =>
      statusForSource(source, ingestLatest.get(source), coverageLatest.get(source), nowMs),
    )
    const healthy = sourceSummaries.filter((r) => r.status === "ok").length
    const warn = sourceSummaries.filter((r) => r.status === "warn").length
    const stale = sourceSummaries.filter((r) => r.status === "stale").length
    const offline = sourceSummaries.filter((r) => r.status === "offline").length
    const worst = sourceSummaries.reduce<HealthBand>((acc, row) => {
      const rank: Record<HealthBand, number> = { offline: 0, stale: 1, warn: 2, ok: 3 }
      return rank[row.status] < rank[acc] ? row.status : acc
    }, "ok")
    const latestIso = sourceSummaries
      .map((row) => row.latestIso)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null
    const detail = [
      healthy > 0 ? `${healthy} ok` : null,
      warn > 0 ? `${warn} warn` : null,
      stale > 0 ? `${stale} stale` : null,
      offline > 0 ? `${offline} offline` : null,
    ]
      .filter(Boolean)
      .join(" · ")

    return {
      key: group.key,
      label: group.label,
      healthy,
      total: sources.length,
      warn,
      stale,
      offline,
      status: worst,
      detail,
      latestIso,
    }
  })
}
