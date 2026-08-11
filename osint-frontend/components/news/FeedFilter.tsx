"use client"

/**
 * The control strip over the news section (#911).
 *
 * Pills rather than dropdowns, for the same reason the console's controls are
 * chips: a closed select hides its own state, and the whole point of a strip
 * at the top of a feed is that you can see what the feed is doing without
 * opening anything.
 *
 * It sits over the news only. Developing is above it and untouched — those
 * stories are pinned because the selector says they qualify, and a filter that
 * could hide them would turn the pin into a suggestion.
 *
 * The count on the right is the honest part: it says how many of the window's
 * stories the current choice is showing, so narrowing to nothing reads as a
 * choice rather than as a page that broke.
 */

export type FeedSort = "newest" | "covered"

//: Only the head of the list fits on a strip, and a strip that wraps to four
//: rows stops being a glance. The rest stay reachable by opening the story.
const PLACES_SHOWN = 8

const REGION_NAMES =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null

/** `KE` reads as nothing to most people; `Kenya` reads as somewhere. The code
 *  stays as the title so a reader can still see what is being matched. */
function placeName(code: string): string {
  try {
    return REGION_NAMES?.of(code) ?? code
  } catch {
    return code
  }
}

export const FEED_SORTS: { key: FeedSort; label: string; hint: string }[] = [
  { key: "newest", label: "Latest", hint: "Most recently filed first" },
  { key: "covered", label: "Most covered", hint: "Most independent owners first" },
]

function Pill({
  on,
  onClick,
  title,
  children,
}: {
  on: boolean
  onClick: () => void
  title?: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={on}
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-[12px] tracking-[0.01em] transition-colors ${
        on
          ? "bg-neutral-100 text-neutral-950"
          : "bg-neutral-900/70 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
      }`}
    >
      {children}
    </button>
  )
}

export function FeedFilter({
  sort,
  onSort,
  categories,
  category,
  onCategory,
  countries,
  country,
  onCountry,
  showing,
  total,
}: {
  sort: FeedSort
  onSort: (sort: FeedSort) => void
  categories: string[]
  category: string | null
  onCategory: (category: string | null) => void
  countries: string[]
  country: string | null
  onCountry: (country: string | null) => void
  showing: number
  total: number
}) {
  //: A place chosen and then pushed off the head of the list by the news
  //: moving on must stay on the strip, or the reader cannot see or clear the
  //: filter that is hiding everything.
  const places = country && !countries.slice(0, PLACES_SHOWN).includes(country)
    ? [country, ...countries.slice(0, PLACES_SHOWN - 1)]
    : countries.slice(0, PLACES_SHOWN)
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-2">
      {FEED_SORTS.map((option) => (
        <Pill
          key={option.key}
          on={sort === option.key}
          title={option.hint}
          onClick={() => onSort(option.key)}
        >
          {option.label}
        </Pill>
      ))}

      {categories.length > 0 && (
        <span className="mx-1 h-4 w-px shrink-0 bg-neutral-800" aria-hidden />
      )}

      {categories.length > 0 && (
        <Pill on={category === null} onClick={() => onCategory(null)}>
          All
        </Pill>
      )}
      {categories.map((name) => (
        <Pill
          key={name}
          on={category === name}
          //: Tapping the active tag clears it. Reaching back to "All" to undo
          //: one tap is a trip the control can save.
          onClick={() => onCategory(category === name ? null : name)}
        >
          {name}
        </Pill>
      ))}

      <span className="ml-auto font-mono text-[10px] tabular-nums tracking-[0.08em] text-neutral-600">
        {showing === total ? `${total}` : `${showing}/${total}`}
      </span>

      {/*: Its own row. Places are a different question from tags, and eight of
          them on the end of the tag row is a strip nobody reads. */}
      {places.length > 0 && (
        <div className="flex w-full flex-wrap items-center gap-2">
          <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-neutral-600">
            where
          </span>
          <Pill on={country === null} onClick={() => onCountry(null)}>
            Anywhere
          </Pill>
          {places.map((code) => (
            <Pill
              key={code}
              on={country === code}
              title={code}
              onClick={() => onCountry(country === code ? null : code)}
            >
              {placeName(code)}
            </Pill>
          ))}
        </div>
      )}
    </div>
  )
}
