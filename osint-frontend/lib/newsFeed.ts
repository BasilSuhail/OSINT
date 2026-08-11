// Narrowing the reading page's feed by tag (#911).
//
// Only the news section is filtered. Developing is pinned above it and is
// deliberately outside the reader's control: those stories are there because
// the selector says they qualify, and a tag filter that could hide them would
// make the pin a suggestion.
//
// The chips are built from the window rather than from a fixed list. A tag
// that no story carries right now is a chip that filters to an empty page, and
// a hard-coded set goes stale the first time the categoriser learns a new word.
//
// Pure, so the ordering and the empty cases are testable without a DOM.

export interface Taggable {
  category: string | null
}

export interface Placeable {
  countries: string[]
}

/**
 * Every tag present in the feed, once each, alphabetically.
 *
 * Alphabetical rather than by frequency on purpose: chips ordered by count
 * reshuffle themselves every time news arrives, and a control that moves under
 * the cursor is a control people stop using.
 */
export function feedCategories<T extends Taggable>(stories: T[]): string[] {
  const seen = new Set<string>()
  for (const story of stories) {
    if (story.category) seen.add(story.category)
  }
  return [...seen].sort()
}

/** The feed narrowed to one tag; `null` means no narrowing at all. */
export function filterByCategory<T extends Taggable>(stories: T[], category: string | null): T[] {
  if (category === null) return stories
  return stories.filter((story) => story.category === category)
}

/**
 * Every place present in the feed, commonest first.
 *
 * By count rather than alphabetically, unlike the tags: there are far more
 * countries than categories, only the first handful fit on the strip, and the
 * ones worth offering are the ones most of the window is about. Ties break
 * alphabetically so the order is stable between refreshes.
 */
export function feedCountries<T extends Placeable>(stories: T[]): string[] {
  const counts = new Map<string, number>()
  for (const story of stories) {
    for (const code of story.countries) {
      counts.set(code, (counts.get(code) ?? 0) + 1)
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([code]) => code)
}

/**
 * The feed narrowed to one place; `null` means no narrowing.
 *
 * A story matches if any of its countries match, because a story that spans
 * three countries is about all of them. A story with no resolved country
 * matches nothing — it is not evidence of being somewhere, and quietly keeping
 * it would make the filter mean less than it says.
 */
export function filterByCountry<T extends Placeable>(stories: T[], country: string | null): T[] {
  if (country === null) return stories
  return stories.filter((story) => story.countries.includes(country))
}
