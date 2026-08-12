"use client"

import { X } from "lucide-react"
import { usePlace, useUpcoming } from "@/lib/queries"
import type { PlaceAnswer, PlaceWeather } from "@/lib/apiClient"
import { distanceLabel, rangeLabel, temperature, windLabel } from "@/lib/placeFormat"
import { whenLabel } from "@/lib/upcomingFormat"
import { usePlaceStore } from "@/stores/placeStore"
import { cn } from "@/lib/utils"
import { CountrySidePanel } from "../CountrySidePanel"

/**
 * What is at a point on the map (#862).
 *
 * A right-click asks what a place *is*; a left-click asks what is *happening*
 * near it. Two questions, two gestures, two screens — and the left-click one
 * is not touched.
 *
 * Above the double rule, slow facts that change on the scale of years. Below
 * it, the score and event list that were already built and that almost nobody
 * could reach, because the only way in was a country chip inside an event card
 * you had to have found first.
 *
 * One label and one value per line, never two columns, and the screen scrolls
 * rather than compressing. A long screen is fine; a crowded one is not.
 */

/** A block the server could not fill says so.
 *
 * Never an empty gap: a section that silently disappears teaches the reader
 * that the console has nothing to say about this place, when what happened is
 * that somebody else's server was slow.
 */
function Unavailable({ what }: { what: string }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-wider text-neutral-600">
      {what} unavailable
    </p>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
      {children}
    </span>
  )
}

function Row({ label, value }: { label: string; value: string | null }) {
  if (!value) return null
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-neutral-500">
        {label}
      </span>
      <span className="text-right text-xs text-neutral-300">{value}</span>
    </div>
  )
}

function Skeleton({ rows }: { rows: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-neutral-800/60" />
      ))}
    </div>
  )
}

/** Numbers people read, not numbers a database prints. */
function formatCount(value: number | null | undefined): string | null {
  if (value == null) return null
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}m`
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}k`
  return String(value)
}

function formatArea(value: number | null | undefined): string | null {
  if (value == null) return null
  return `${Math.round(value).toLocaleString("en-GB")} km²`
}

/** Two sentences, because the screen asks what a place is, not for its history.
 *
 * Splitting on a full stop followed by a space keeps abbreviations intact well
 * enough for an opening paragraph, and the link out carries the rest. */
/** "next pass in 14 hours" — rounded, because the arithmetic is finer than the
 * question. The moment the spacecraft is overhead is not the same instant as
 * the timestamp printed on a product, which is the sensing start of a whole
 * datastrip; at this resolution the difference does not survive rounding. */
function nextPassLabel(pass: { platform: string; hours_away: number }): string {
  const hours = pass.hours_away
  if (hours < 1) return `${pass.platform} overhead within the hour`
  if (hours < 36) return `${pass.platform} passes in ${Math.round(hours)}h`
  return `${pass.platform} passes in ${Math.round(hours / 24)} days`
}

function twoSentences(extract: string): string {
  const parts = extract.split(/(?<=\.)\s+/)
  return parts.slice(0, 2).join(" ")
}

/** Conditions over the coordinate (#932).
 *
 * The temperature is the headline because it is the thing being asked. The
 * high and low carry the window they cover — normally a day, shorter at the
 * end of a forecast — because a range with no window is a claim rather than a
 * measurement.
 */
function Weather({ weather }: { weather: PlaceWeather }) {
  const now = temperature(weather.temperature_c)
  const high = temperature(weather.high_c)
  const low = temperature(weather.low_c)
  const window = rangeLabel(weather.range_hours)
  return (
    <>
      <div className="flex items-baseline gap-2.5">
        <span className="text-lg font-medium text-neutral-100">{now ?? "—"}</span>
        {weather.conditions && (
          <span className="text-xs text-neutral-400">{weather.conditions}</span>
        )}
      </div>
      <Row label="Wind" value={windLabel(weather.wind_ms, weather.wind_from_deg)} />
      <Row
        label="Humidity"
        value={weather.humidity_pct == null ? null : `${weather.humidity_pct}%`}
      />
      <Row
        label={window ? `High · low (${window})` : "High · low"}
        value={high && low ? `${high} · ${low}` : null}
      />
    </>
  )
}

/** What is scheduled in this country (#934).
 *
 * The only forward-looking block on a screen that is otherwise entirely past
 * tense. Its own request, so a slow calendar cannot delay the facts above it —
 * which is why it has its own skeleton rather than sharing the panel's.
 *
 * A day with several contests arrives already collapsed by the server and
 * carries its count. Naming it after one member put "2026 Iowa elections" at
 * the head of fifty-seven American races.
 */
function Upcoming({ iso }: { iso: string }) {
  const { upcoming, isLoading } = useUpcoming(iso)

  if (isLoading) return <Skeleton rows={2} />
  if (!upcoming || upcoming.degraded) return <Unavailable what="Schedule" />
  if (upcoming.entries.length === 0) {
    return (
      <p className="font-mono text-[10px] uppercase tracking-wider text-neutral-600">
        Nothing scheduled in the next {upcoming.days} days
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      {upcoming.entries.map((entry) => (
        <div
          key={`${entry.starts_on}-${entry.headline}`}
          className="flex items-baseline justify-between gap-3"
        >
          <span className="min-w-0 text-xs text-neutral-300">
            {entry.headline}
            {entry.count > 1 && (
              <span className="ml-1.5 font-mono text-[10px] uppercase tracking-wider text-neutral-600">
                one day
              </span>
            )}
          </span>
          <span className="shrink-0 text-right font-mono text-[10px] uppercase tracking-wider text-neutral-500">
            {whenLabel(entry.starts_on)}
          </span>
        </div>
      ))}
    </div>
  )
}

function Identity({ answer, onClose }: { answer: PlaceAnswer; onClose: () => void }) {
  const country = answer.country
  const point = answer.point
  const city = answer.city
  //: The headline is the smallest true thing (#932). Somebody who right-clicked
  //: one spot is standing in a town, not in a country, and the country they are
  //: standing in is the second sentence rather than the first.
  const headline = city?.name ?? (country ? country.name : "Open water")
  const beneath = city
    ? [country?.name, distanceLabel(city.distance_km)].filter(Boolean).join(" · ")
    : country
      ? country.iso2
      : point
        ? `${point.lat.toFixed(4)}, ${point.lon.toFixed(4)}`
        : "no location"
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex items-center gap-2.5">
        {country && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`https://flagcdn.com/32x24/${country.iso2.toLowerCase()}.png`}
            alt=""
            width={32}
            height={24}
            className="rounded-sm border border-neutral-800"
          />
        )}
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-medium text-neutral-100">{headline}</span>
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
            {beneath}
          </span>
          {answer.government?.type && (
            <span className="mt-0.5 text-xs text-neutral-400">{answer.government.type}</span>
          )}
          {country?.near_border && (
            // The polygon is only so good, and a screen that names a country
            // without saying it is standing on the line is sometimes quietly
            // wrong.
            <span className="mt-1 font-mono text-[9px] uppercase tracking-wider text-amber-300/80">
              {country.border_distance_km} km from the border
            </span>
          )}
        </div>
      </div>
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="shrink-0 text-neutral-500 hover:text-neutral-200"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

export function PlacePanel() {
  const target = usePlaceStore((s) => s.target)
  const close = usePlaceStore((s) => s.close)
  const { place, isLoading } = usePlace(target)

  if (!target) return null

  const degraded = new Set(place?.degraded ?? [])
  const iso = place?.country?.iso2 ?? null

  return (
    <div className="absolute inset-0 overflow-y-auto bg-neutral-950 p-3">
      <div className="flex flex-col gap-4 rounded-md border border-neutral-800 bg-neutral-950/95 p-4">
        {isLoading || !place ? (
          <Skeleton rows={8} />
        ) : (
          <>
            <Identity answer={place} onClose={close} />

            {/* Where you are, before which country you are in (#932). Both
                blocks are about the point rather than the nation, which is the
                order the gesture asks for. */}
            {place.point && (
              <div className="flex flex-col border-t border-neutral-800 pt-3">
                {degraded.has("city") ? (
                  <Unavailable what="Nearest settlement" />
                ) : place.city ? (
                  <>
                    <Row label="Region" value={place.city.region} />
                    <Row label="Population" value={formatCount(place.city.population)} />
                    <Row label="Distance" value={distanceLabel(place.city.distance_km)} />
                  </>
                ) : (
                  // Not a failure. Ocean, desert and tundra are places, and
                  // "unavailable" would send the reader back to try again.
                  <p className="font-mono text-[10px] uppercase tracking-wider text-neutral-600">
                    No settlement within 100 km
                  </p>
                )}
              </div>
            )}

            {place.point && (
              <div className="flex flex-col gap-1.5 border-t border-neutral-800 pt-3">
                <SectionLabel>Weather here</SectionLabel>
                {degraded.has("weather") || !place.weather ? (
                  <Unavailable what="Weather" />
                ) : (
                  <Weather weather={place.weather} />
                )}
              </div>
            )}

            <div className="flex flex-col border-t border-neutral-800 pt-3">
              {degraded.has("profile") && degraded.has("government") ? (
                <Unavailable what="Country facts" />
              ) : (
                <>
                  <Row label="Head of state" value={place.government?.head_of_state ?? null} />
                  <Row
                    label="Head of government"
                    value={place.government?.head_of_government ?? null}
                  />
                  <Row label="Capital" value={place.profile?.capital ?? null} />
                  <Row label="Population" value={formatCount(place.profile?.population)} />
                  <Row
                    label="Languages"
                    value={place.profile?.languages.join(", ") || null}
                  />
                  <Row
                    label="Currency"
                    value={place.profile?.currencies.join(", ") || null}
                  />
                  <Row label="Area" value={formatArea(place.profile?.area_km2)} />
                </>
              )}
            </div>

            <div className="flex flex-col gap-1.5 border-t border-neutral-800 pt-3">
              {degraded.has("summary") || !place.summary?.extract ? (
                <Unavailable what="Summary" />
              ) : (
                <>
                  <p className="text-xs leading-relaxed text-neutral-300">
                    {twoSentences(place.summary.extract)}
                  </p>
                  {place.summary.url && (
                    <a
                      href={place.summary.url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-[10px] uppercase tracking-wider text-neutral-500 hover:text-neutral-300"
                    >
                      Read more →
                    </a>
                  )}
                </>
              )}
            </div>

            {/* Between what the place is and what it looked like from orbit:
                what is coming. Only for a country — an election belongs to a
                state, not to a point on open water. */}
            {iso && (
              <div className="flex flex-col gap-1.5 border-t border-neutral-800 pt-3">
                <SectionLabel>Coming up</SectionLabel>
                <Upcoming iso={iso} />
              </div>
            )}

            <div className="flex flex-col gap-1.5 border-t border-neutral-800 pt-3">
              <SectionLabel>Latest clear pass</SectionLabel>
              {degraded.has("imagery") || !place.imagery ? (
                <Unavailable what="Satellite imagery" />
              ) : (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={place.imagery.url}
                    alt=""
                    className="w-full rounded-md border border-neutral-800 bg-neutral-900"
                  />
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">
                      {[
                        place.imagery.captured_at?.slice(0, 10),
                        // Sentinel-2's visual band is often half white, and a
                        // white square with no explanation reads as a broken
                        // image rather than as weather.
                        place.imagery.cloud_cover_pct == null
                          ? null
                          : `${place.imagery.cloud_cover_pct.toFixed(0)}% cloud`,
                        "10 m",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <a
                      href={place.imagery.full_url}
                      target="_blank"
                      rel="noreferrer"
                      className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-neutral-500 hover:text-neutral-300"
                    >
                      Full scene →
                    </a>
                  </div>
                  {/* Why the picture is as old as it is. Without this, nine
                      days old and two days old look like the same fact, and
                      the reader cannot tell whether waiting would help. */}
                  {place.next_pass && (
                    <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">
                      {nextPassLabel(place.next_pass)}
                    </span>
                  )}
                </>
              )}
            </div>

            {/* Attribution is a licence condition on two of these sources, not
                a courtesy, and it belongs beside what it covers. */}
            <p className="border-t border-neutral-800 pt-3 font-mono text-[9px] uppercase tracking-wider text-neutral-600">
              Copernicus · Wikipedia · Wikidata · Natural Earth · OpenStreetMap · MET Norway
            </p>
          </>
        )}
      </div>

      {/* The divider. Above it, what this place is. Below it, what is
          happening there — the panel that was already built and that a reader
          could barely reach. */}
      {iso && (
        <div className={cn("mt-3 border-t-2 border-neutral-800 pt-3")}>
          <CountrySidePanel country={iso} onClose={close} />
        </div>
      )}
    </div>
  )
}
