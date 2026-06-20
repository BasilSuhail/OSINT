"use client"

import { useEffect, useState } from "react"

/**
 * Subscribe to a CSS media query. Returns true when the query matches.
 * SSR-safe: returns `false` during the initial server render, then updates
 * after hydration. Components that need to swap layouts on mount should
 * accept the brief flicker; it's invisible at first paint.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    if (typeof window === "undefined") return
    const mql = window.matchMedia(query)
    setMatches(mql.matches)
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches)
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [query])

  return matches
}
