"use client"

import { useMemo, useState } from "react"
import { Check, ChevronsUpDown, RotateCcw, Search, SlidersHorizontal, X } from "lucide-react"
import { useEvents } from "@/app/providers"
import { sourceFiltersForPane, type Pane } from "@/lib/types"
import type { FilterStore } from "@/stores/createFilterStore"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Input } from "@/components/ui/input"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

interface FilterRailProps {
  pane: Pane
  side: "left" | "right"
  useStore: FilterStore
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function FilterRail({ pane, side, useStore, open, onOpenChange }: FilterRailProps) {
  const allEvents = useEvents()
  const sources = useStore((s) => s.sources)
  const severity = useStore((s) => s.severity)
  const countries = useStore((s) => s.countries)
  const keyword = useStore((s) => s.keyword)
  const showSatellites = useStore((s) => s.showSatellites)
  const satelliteGroup = useStore((s) => s.satelliteGroup)
  const showCelestial = useStore((s) => s.showCelestial)
  const toggleSource = useStore((s) => s.toggleSource)
  const setSeverity = useStore((s) => s.setSeverity)
  const toggleCountry = useStore((s) => s.toggleCountry)
  const setKeyword = useStore((s) => s.setKeyword)
  const toggleSatellites = useStore((s) => s.toggleSatellites)
  const setSatelliteGroup = useStore((s) => s.setSatelliteGroup)
  const toggleCelestial = useStore((s) => s.toggleCelestial)
  const reset = useStore((s) => s.reset)

  const isGlobe = pane === "globe"

  const [countryOpen, setCountryOpen] = useState(false)

  /** Only show source toggles that render on this pane. */
  const paneFilters = useMemo(() => sourceFiltersForPane(pane), [pane])

  const distinctCountries = useMemo(() => {
    const set = new Set<string>()
    for (const ev of allEvents) if (ev.country) set.add(ev.country)
    return Array.from(set).sort()
  }, [allEvents])

  const activeCount =
    paneFilters.filter((f) => !sources[f.key]).length +
    (severity[0] > 0 || severity[1] < 1 ? 1 : 0) +
    (countries.length > 0 ? 1 : 0) +
    (keyword.trim() ? 1 : 0) +
    (isGlobe && !showSatellites ? 1 : 0) +
    (isGlobe && !showCelestial ? 1 : 0)

  const isLeft = side === "left"

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-y-0 z-20 flex items-stretch",
        isLeft ? "left-0" : "right-0",
      )}
    >
      {/* Collapsed icon strip */}
      <div
        className={cn(
          "pointer-events-auto flex w-11 flex-col items-center gap-2 bg-neutral-950/70 py-3 backdrop-blur-sm",
          isLeft ? "order-first border-r border-neutral-800" : "order-last border-l border-neutral-800",
        )}
      >
        <button
          type="button"
          aria-label={open ? "Collapse filters" : "Expand filters"}
          aria-expanded={open}
          onClick={() => onOpenChange(!open)}
          className={cn(
            "relative grid h-8 w-8 place-items-center rounded-md border text-neutral-300 transition-colors",
            open
              ? "border-neutral-600 bg-neutral-800 text-neutral-50"
              : "border-neutral-800 hover:border-neutral-600 hover:text-neutral-100",
          )}
        >
          <SlidersHorizontal className="h-4 w-4" />
          {activeCount > 0 && (
            <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-emerald-500 px-1 font-mono text-[10px] font-medium text-neutral-950">
              {activeCount}
            </span>
          )}
        </button>
        {/* Source dots as quick toggles */}
        {paneFilters.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-label={`${f.label} ${sources[f.key] ? "on" : "off"}`}
            onClick={() => toggleSource(f.key)}
            className="grid h-8 w-8 place-items-center rounded-md transition-colors hover:bg-neutral-800"
          >
            <span
              className="h-2.5 w-2.5 rounded-full transition-opacity"
              style={{ backgroundColor: f.hex, opacity: sources[f.key] ? 1 : 0.25 }}
            />
          </button>
        ))}
        {isGlobe && (
          <button
            type="button"
            aria-label={`Satellites ${showSatellites ? "on" : "off"}`}
            onClick={toggleSatellites}
            className="grid h-8 w-8 place-items-center rounded-md transition-colors hover:bg-neutral-800"
          >
            <span
              className="h-2.5 w-2.5 rounded-full transition-opacity"
              style={{ backgroundColor: "#22d3ee", opacity: showSatellites ? 1 : 0.25 }}
            />
          </button>
        )}
        {isGlobe && (
          <button
            type="button"
            aria-label={`Sun & Moon ${showCelestial ? "on" : "off"}`}
            onClick={toggleCelestial}
            className="grid h-8 w-8 place-items-center rounded-md transition-colors hover:bg-neutral-800"
          >
            <span
              className="h-2.5 w-2.5 rounded-full transition-opacity"
              style={{ backgroundColor: "#fde68a", opacity: showCelestial ? 1 : 0.25 }}
            />
          </button>
        )}
      </div>

      {/* Expanded panel */}
      {open && (
        <div
          className={cn(
            "pointer-events-auto flex w-[280px] flex-col gap-4 overflow-y-auto bg-neutral-950/85 p-4 backdrop-blur-md",
            isLeft ? "border-r border-neutral-800" : "border-l border-neutral-800",
          )}
        >
          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              {isLeft ? "Map filters" : "Globe filters"}
            </span>
            <button
              type="button"
              aria-label="Close panel"
              onClick={() => onOpenChange(false)}
              className="text-neutral-500 hover:text-neutral-200"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Source toggles */}
          <div className="flex flex-col gap-1.5">
            {paneFilters.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => toggleSource(f.key)}
                className={cn(
                  "flex items-center gap-2.5 rounded-md border px-2.5 py-2 text-left text-[13px] transition-colors",
                  sources[f.key]
                    ? "border-neutral-700 bg-neutral-800/60 text-neutral-100"
                    : "border-neutral-800/60 text-neutral-500 hover:border-neutral-700",
                )}
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: f.hex, opacity: sources[f.key] ? 1 : 0.3 }}
                />
                <span className="flex-1">{f.label}</span>
                <span className="font-mono text-[10px] uppercase text-neutral-500">{f.key}</span>
              </button>
            ))}
            {isGlobe && (
              <>
                <button
                  type="button"
                  onClick={toggleSatellites}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md border px-2.5 py-2 text-left text-[13px] transition-colors",
                    showSatellites
                      ? "border-cyan-800 bg-cyan-950/30 text-cyan-100"
                      : "border-neutral-800/60 text-neutral-500 hover:border-neutral-700",
                  )}
                >
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: "#22d3ee", opacity: showSatellites ? 1 : 0.3 }}
                  />
                  <span className="flex-1">Live satellites</span>
                  <span className="font-mono text-[10px] uppercase text-neutral-500">TLE</span>
                </button>
                {showSatellites && (
                  <div className="flex flex-wrap gap-1 pl-1">
                    {(["stations", "visual", "active"] as const).map((g) => (
                      <button
                        key={g}
                        type="button"
                        onClick={() => setSatelliteGroup(g)}
                        className={cn(
                          "rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest transition-colors",
                          satelliteGroup === g
                            ? "border-cyan-600 bg-cyan-950/40 text-cyan-200"
                            : "border-neutral-800 text-neutral-500 hover:border-neutral-700 hover:text-neutral-300",
                        )}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                )}
                <button
                  type="button"
                  onClick={toggleCelestial}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md border px-2.5 py-2 text-left text-[13px] transition-colors",
                    showCelestial
                      ? "border-amber-800 bg-amber-950/20 text-amber-100"
                      : "border-neutral-800/60 text-neutral-500 hover:border-neutral-700",
                  )}
                >
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: "#fde68a", opacity: showCelestial ? 1 : 0.3 }}
                  />
                  <span className="flex-1">Sun &amp; Moon</span>
                  <span className="font-mono text-[10px] uppercase text-neutral-500">EPH</span>
                </button>
              </>
            )}
          </div>

          {/* Severity */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                Severity
              </span>
              <span className="font-mono text-[11px] text-neutral-300">
                {severity[0].toFixed(2)} – {severity[1].toFixed(2)}
              </span>
            </div>
            <Slider
              value={severity}
              min={0}
              max={1}
              step={0.01}
              onValueChange={(v) => {
                if (Array.isArray(v)) setSeverity([v[0], v[1]])
              }}
              aria-label="Severity range"
            />
          </div>

          {/* Country multiselect */}
          <div className="flex flex-col gap-2">
            <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Country
            </span>
            <Popover open={countryOpen} onOpenChange={setCountryOpen}>
              <PopoverTrigger
                render={
                  <Button
                    variant="outline"
                    role="combobox"
                    aria-expanded={countryOpen}
                    className="h-9 justify-between border-neutral-700 bg-neutral-900 font-mono text-xs text-neutral-200 hover:bg-neutral-800 hover:text-neutral-100"
                  />
                }
              >
                {countries.length > 0 ? `${countries.length} selected` : "All countries"}
                <ChevronsUpDown className="h-3.5 w-3.5 opacity-50" />
              </PopoverTrigger>
              <PopoverContent
                align="start"
                className="w-[248px] border-neutral-700 bg-neutral-900 p-0"
              >
                <Command className="bg-neutral-900">
                  <CommandInput placeholder="Search country…" className="text-xs" />
                  <CommandList>
                    <CommandEmpty className="py-4 text-center text-xs text-neutral-500">
                      No country found.
                    </CommandEmpty>
                    <CommandGroup>
                      {distinctCountries.map((c) => (
                        <CommandItem
                          key={c}
                          value={c}
                          onSelect={() => toggleCountry(c)}
                          className="font-mono text-xs"
                        >
                          <Check
                            className={cn(
                              "mr-2 h-3.5 w-3.5",
                              countries.includes(c) ? "opacity-100" : "opacity-0",
                            )}
                          />
                          {c}
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
            {countries.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {countries.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => toggleCountry(c)}
                    className="flex items-center gap-1 rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px] text-neutral-300 hover:bg-neutral-700"
                  >
                    {c}
                    <X className="h-2.5 w-2.5" />
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Keyword */}
          <div className="flex flex-col gap-2">
            <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Keyword
            </span>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-neutral-500" />
              <Input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="Filter by keyword…"
                className="h-9 border-neutral-700 bg-neutral-900 pl-8 font-mono text-xs text-neutral-200 placeholder:text-neutral-600"
              />
            </div>
          </div>

          <Button
            variant="ghost"
            onClick={reset}
            className="mt-auto h-8 justify-center gap-2 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset filters
          </Button>
        </div>
      )}
    </div>
  )
}
