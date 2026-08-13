# The console on a phone

Design for #942.

## Why

`make share` starts the stack bound to the local network so the console can
be opened on a phone that is not the machine running it. What arrives on that
phone is the desktop console with most of its controls either absent or too
small to hit.

This is not a responsive pass over a layout that never had one. `SplitLayout`
already switches at 900px, and the switch already produces a fullscreen map
with a `map | panel` pill switcher. What it produces is a stub: the omnibox is
not rendered below the breakpoint at all, the filter rail and the time
scrubber render at desktop size on top of a screen with four short edges, and
the deck opens as a full-bleed panel that hides the map it describes.

The narrow layout needs finishing, not inventing.

## Shape

Map first. One search bar across the top. Everything else put away until it
is asked for.

```
┌────────────────────┐
│ 🔍 search or ask   │  omnibox, full width, safe-area inset
│                    │
│                    │
│       [ map ]    ⚙ │  rail trigger, one icon, right edge
│                    │
│                ▔▔  │  scrubber handle, lifted clear of the sheet
│ ──────  situation  │  sheet at peek
└────────────────────┘
```

## Components

### `lib/narrowLayout.ts` — the arithmetic

Everything about the layout that can be stated as a number lives here, as
pure functions with no React and no DOM. This is the only part of the work a
test can reach.

```ts
/** Below this the console is a phone, not a narrow window. */
export const NARROW_MAX_PX = 820
export const NARROW_QUERY = `(max-width: ${NARROW_MAX_PX}px)`

export type Detent = "peek" | "half" | "full"

/** Sheet height in px for each detent, given the viewport height. */
export function detentHeights(viewportH: number): Record<Detent, number>

/** Which detent a drag that ended at `height` px lands on. Nearest wins;
 *  a fast flick overrides distance and moves one detent in its direction. */
export function snapDetent(height: number, viewportH: number, velocity: number): Detent
```

`PEEK_PX` is 56 — a grip and a card title, and nothing else. `half` is
`0.5 * viewportH`. `full` is `viewportH - TOP_STRIP_PX`, so the omnibox is
never covered by the thing it opens.

`FLICK_PX_PER_S` is the velocity above which a drag is read as a throw rather
than a placement. A throw moves exactly one detent in the direction of
travel; it does not skip from peek to full, because a gesture that overshoots
by one screen is a gesture that has to be undone.

The initial panel state for a narrow first paint is also arithmetic:

```ts
/** What `panelLayout` starts as when the console opens on a phone: the
 *  scrubber away, the rail closed, the deck at peek. */
export function narrowInitialPanels(): { bottom: boolean; right: boolean }
```

### `components/BottomSheet.tsx` — the surface

Wraps children in a sheet dragged by a grip. Knows nothing about the deck:
its props are `detent`, `onDetentChange` and `children`. `CardDeck` goes
inside it unchanged.

Drag is bound to the grip alone, never to the sheet body. Three gestures
already have claims on a touch inside that rectangle — the map's one-finger
pan, `CardDeck`'s two-finger page swipe (`CardDeck.tsx:113`), and a card's
own vertical scroll. A grip-only drag collides with none of them, and the
alternative — a body drag that defers to scroll position — is the class of
gesture code that works on one phone and not the next.

Animation uses `framer-motion`, already a dependency. Height is animated,
not `transform: scale`, because the deck inside has to lay out at the height
it ends up with.

The sheet publishes its own occupied height as `--sheet-peek` on the layout
root, so the scrubber handle can sit above it without either one measuring
the other.

### `Omnibox` — a `narrow` variant

The box is unchanged in what it does; only its box model differs. Today it
positions itself at the top of the left column at `PANEL_WIDTH`. On narrow it
is `inset-x-2`, top-anchored under the safe-area inset, and its dropdown is
`max-height: 60dvh` with the viewport's width rather than the column's.

The prop is `narrow?: boolean`, passed by `SplitLayout` from the media query
it already computes. It is not read from a store: which layout the box is in
is a fact about where it was rendered, and a component that asks a store
where it is can be rendered somewhere that disagrees.

### `SplitLayout` — the narrow branch

- Renders `<Omnibox narrow />` instead of rendering nothing.
- Deletes the `map | panel` pill switcher. The sheet's grip is the control
  that used to be, and two controls for one thing is how the top strip got
  crowded.
- Renders the deck inside `BottomSheet` instead of inside a full-bleed
  `FloatingPanel`.
- Does not render the desktop collapse handle.
- Keeps `--panel-width` at 0, so map-level overlays use the full width.

The `activePane` state the pill switcher drove goes with it. What it was for
survives: tapping a marker on a phone has to show the card it opens, so
selecting an event raises the sheet from peek to half rather than switching
a pane. Half rather than full, because the marker that was tapped stays on
screen — a card that hides what it is about is the failure the full-bleed
panel already had.

`SystemMonitor` on narrow shows the dot and the clock and drops the counts —
the counts are the first thing the monitor panel says once it is opened, and
the corner is 40px of a 390px-wide strip that the search bar has the rest of.

### `MapPane` — the rail

`FilterRail` starts closed on narrow and opens as a full-height right drawer
from a single 44px icon on the map's right edge. The rail's own open/close
plumbing (`open`, `onOpenChange`) is unchanged; what changes is the initial
value and the width it opens to.

`TimeScrubber` starts hidden — `panelLayout.bottom` false — and its existing
handle is offset by `--sheet-peek` so it clears the sheet.

### `app/layout.tsx`

`viewportFit: "cover"`, so `env(safe-area-inset-*)` resolves to real values.
`maximumScale: 1` stays: the map owns pinch, and a page that zooms under the
map is a page whose controls drift off the edge.

## Data flow

Nothing new. The narrow layout renders the same components against the same
stores; the sheet's detent is local state in `SplitLayout` because nothing
outside the narrow branch has an opinion about it.

## Errors

There is no new failure mode. The sheet with a zero-height viewport (a phone
mid-rotation reports one for a frame) clamps to the peek height rather than
dividing by it; `detentHeights` is total for every input including 0.

## Testing

`__tests__/narrowLayout.test.ts`, in the style of the rest of the suite —
pure functions, no DOM:

- `detentHeights` is monotonic: peek < half < full, for a range of viewport
  heights including 0 and a very tall one.
- `full` leaves the top strip uncovered.
- `snapDetent` picks the nearest detent for a slow drag.
- `snapDetent` moves exactly one detent for a flick, in the flick's
  direction, and does not skip.
- `snapDetent` at the extremes cannot leave the range.
- `narrowInitialPanels` puts the scrubber away and the rail closed.

**What no test here covers.** Whether the bar is reachable with a thumb,
whether the sheet feels like a sheet, whether the map is still legible with
the peek over it. There is no browser automation and no DOM test
infrastructure in this repository, so the visual result ships unverified and
has to be opened on a phone through `make share` and looked at.

## Not in this

No separate mobile route. No web app manifest, no install prompt, no service
worker, no offline mode. No landscape-specific layout — the same rules apply
to a short wide screen, and if that reads badly it is its own change.
