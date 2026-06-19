"use client"

import useSWR from "swr"
import { useMemo } from "react"
import { countryFillColor } from "./types"
import type { LatestScore } from "./queries"

const GEO_URL =
  "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"

type Geometry =
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] }

interface Feature {
  type: "Feature"
  properties: Record<string, unknown>
  geometry: Geometry
}

export interface CountriesGeo {
  type: "FeatureCollection"
  features: Feature[]
}

const ISO_KEYS = ["ISO3166-1-Alpha-2", "ISO_A2", "iso_a2", "ISO_A2_EH", "WB_A2"]

export function isoOf(props: Record<string, unknown>): string | null {
  for (const k of ISO_KEYS) {
    const v = props[k]
    if (typeof v === "string" && v.length === 2 && v !== "-99") return v.toUpperCase()
  }
  return null
}

const NAME_KEYS = ["ADMIN", "name", "NAME", "ISO3166-1-Alpha-3"]

export function nameOf(props: Record<string, unknown>): string {
  for (const k of NAME_KEYS) {
    const v = props[k]
    if (typeof v === "string" && v) return v
  }
  return ""
}

function centroidOf(geom: Geometry): [number, number] {
  let sx = 0
  let sy = 0
  let n = 0
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates
  for (const poly of polys) {
    const ring = poly[0]
    for (const [x, y] of ring) {
      sx += x
      sy += y
      n++
    }
  }
  return n > 0 ? [sx / n, sy / n] : [0, 0]
}

async function fetchGeo(): Promise<CountriesGeo> {
  const res = await fetch(GEO_URL)
  if (!res.ok) throw new Error("Failed to load country geometry")
  return (await res.json()) as CountriesGeo
}

export function useCountriesGeo() {
  const { data } = useSWR("countries-geo", fetchGeo, {
    revalidateOnFocus: false,
    revalidateIfStale: false,
    dedupingInterval: Infinity,
  })

  const centroids = useMemo(() => {
    const map = new Map<string, [number, number]>()
    if (!data) return map
    for (const f of data.features) {
      const iso = isoOf(f.properties)
      if (iso) map.set(iso, centroidOf(f.geometry))
    }
    return map
  }, [data])

  return { geo: data ?? null, centroids }
}

/** Merge latest scores into the geojson as a `__fill` paint property. */
export function useScoredGeo(byCountry: Map<string, LatestScore>): CountriesGeo | null {
  const { geo } = useCountriesGeo()
  return useMemo(() => {
    if (!geo) return null
    return {
      type: "FeatureCollection",
      features: geo.features.map((f) => {
        const iso = isoOf(f.properties)
        const score = iso ? byCountry.get(iso)?.score : undefined
        return {
          ...f,
          properties: {
            ...f.properties,
            __iso: iso,
            __fill: score !== undefined ? countryFillColor(score) : "rgba(0,0,0,0)",
            __score: score ?? -1,
          },
        }
      }),
    }
  }, [geo, byCountry])
}

export { useCountriesGeo as useGeo }
