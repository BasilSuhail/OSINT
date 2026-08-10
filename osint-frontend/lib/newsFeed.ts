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
