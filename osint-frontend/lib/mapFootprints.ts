import type { VisibleEvent } from "./queries"
import { footprintFeatures, type HazardFeature } from "./hazardSymbols"

export interface HazardFootprintCollection {
  type: "FeatureCollection"
  features: Array<{
    type: "Feature"
    properties: { color: string; fillOpacity: number; selected: boolean }
    geometry: HazardFeature["geometry"]
  }>
}

export function hazardFootprintCollections(
  positioned: Array<{ ev: VisibleEvent }>,
  selectedEventId: VisibleEvent["id"] | null,
): {
  ambient: HazardFootprintCollection
  selected: HazardFootprintCollection
} {
  const ambient: HazardFootprintCollection["features"] = []
  const selected: HazardFootprintCollection["features"] = []

  for (const { ev } of positioned) {
    if (ev.category !== "hazard" && ev.category !== "weather") continue
    const isSelected = ev.id === selectedEventId
    for (const f of footprintFeatures(ev, isSelected)) {
      const feature = {
        type: "Feature" as const,
        properties: { ...f.properties, selected: isSelected },
        geometry: f.geometry,
      }
      if (isSelected) selected.push(feature)
      else ambient.push(feature)
    }
  }

  return {
    ambient: { type: "FeatureCollection", features: ambient },
    selected: { type: "FeatureCollection", features: selected },
  }
}
