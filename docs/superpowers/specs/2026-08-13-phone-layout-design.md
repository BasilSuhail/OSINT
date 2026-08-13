# The console on a phone

Design for #942, revised by #944 — the first pass answered the narrow layout
with a bottom sheet, and a second console to learn is not what a phone needs.

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

The same console, narrower, with every panel put away on arrival. The deck is
the left column it already is, the filter rail stays docked right, the
scrubber stays along the bottom, and each keeps the handle it already had.

An earlier pass replaced the deck with a bottom sheet. That was a second
console to learn: a reader who knows this one on a laptop had to learn where
everything went a second time, and the phone is where they have least
patience for that. Removed.

```
┌────────────────────┐
│ 🔍 ask or find   ✨ │  omnibox, 48px, safe-area inset
│                    │
│                  › │  deck handle, clamped on screen
│      [ map ]     ⚙ │  rail handle, right edge
│                    │
│         ▔▔         │  scrubber handle, centred
└────────────────────┘
```

Opening the deck gives it the width of the screen minus the margin the panels
already use. That is not a phone layout so much as the wide one running out
of room to be anything else, which is the point.

## Components

### `lib/narrowLayout.ts`

Two things, no React and no DOM, so a test can reach them: the breakpoint, and
what the four edges hold on arrival.

```ts
/** Below this the console is a phone, not a narrow window. */
export const NARROW_MAX_PX = 820
export const NARROW_QUERY = `(max-width: ${NARROW_MAX_PX}px)`

/** Deck, scrubber and rail all away. `top` is absent: it is the omnibox's
 *  own result list, and it is empty until something is typed. */
export function narrowInitialPanels(): { left: boolean; bottom: boolean; right: boolean }
```

Applied once, on the first narrow paint. Where the console arrives, not a rule
about where it stays — putting any panel back keeps it back.

### `lib/layout.ts` — two more constants

`NARROW_PANEL_WIDTH` is `calc(100vw - 1.5rem)`: `PANEL_WIDTH`'s 360px floor is
wider than the screen it would sit on. `NARROW_COLUMN_TOP` is the same idea
for the vertical — the bar is shorter on a phone, and the notch is above it.

`SplitLayout` picks one of each into `columnWidth` and `columnTop` and every
consumer reads those, so the deck, the pop-up and the scrubber cannot disagree
about where the column is.

### `Omnibox` — a `narrow` variant

Unchanged in what it does; only its box model differs. On narrow it spans the
screen at the same 12px margin the column uses, in a fixed 48px row with 40px
controls inside it. The two-word ask button becomes an icon and the results
chevron is absent rather than greyed while there is nothing to show — a
disabled control still takes its width, and that width is the difference
between a box a place name fits in and one it does not.

The input is 16px there. Below that, mobile Safari zooms the page to the
focused field on its own and the console never zooms back out.

The prop is `narrow?: boolean`, passed by `SplitLayout` from the media query
it already computes. Not read from a store: which layout the box is in is a
fact about where it was rendered, and a component that asks a store where it
is can be rendered somewhere that disagrees.

### `SplitLayout` — one stage, not two

The narrow branch is gone. There is one layered stage, and `isNarrow` changes
measurements inside it rather than choosing between two trees.

- the deck is the same `FloatingPanel` in the same left column, at
  `columnWidth`
- the pop-up stacks on the column instead of standing beside it — there is no
  beside — one z-layer up. Still not a page of the deck: the deck is
  underneath, unchanged, and closing the pop-up puts the reader back
- `--panel-width` never doubles for the pop-up on narrow
- the collapse handle is clamped to stay on screen, and sits a third of the
  way down rather than halfway, because the rail's handle is centred on the
  same edge it is clamped to
- tapping a marker opens the column, since the card it fills would otherwise
  land in a panel that is not on screen

`SystemMonitor` on narrow drops below the bar and shows the worst band only.

### `MapPane` — rail and scrubber

Both keep their edges and their handles. `FilterRail`'s handle is a square
button on narrow rather than a tall thin tab — widened for a thumb and kept
tall it read as a small panel floating against nothing — and its panel never
grows wider than the screen. `TimeScrubber` drops the four playback speeds,
which do not fit beside the slider the bar exists for, and shows the end of
the window rather than both ends.

### `app/layout.tsx`

`viewportFit: "cover"`, so `env(safe-area-inset-*)` resolves to real values.
`maximumScale: 1` stays: the map owns pinch, and a page that zooms under the
map is a page whose controls drift off the edge.

## Data flow

Nothing new, and nothing new to store. The panels already live in
`panelLayout`; the narrow layout writes their initial values once and then
uses the same toggles the wide one does — including the WASD keys, which keep
working on a phone with a keyboard attached.

## Errors

No new failure mode. Nothing here measures anything at runtime: the widths are
CSS expressions and the initial state is a constant, so there is no frame in
which two things disagree about a number one of them has not read yet.

## Testing

`__tests__/narrowLayout.test.ts`, in the style of the rest of the suite:

- `NARROW_QUERY` is a max-width query built from `NARROW_MAX_PX`
- the breakpoint sits below the width a laptop window is usually dragged to
- `narrowInitialPanels` puts deck, rail and scrubber away
- it says nothing about `top`, which is the omnibox's own

**What no test here covers.** Whether the bar is reachable with a thumb,
whether a full-width deck still leaves the map usable, whether the clamped
handle lands somewhere a thumb can find. There is no browser automation and no
DOM test infrastructure in this repository, so the visual result ships
unverified and has to be opened on a phone through the shared link and looked
at.

## Not in this

No separate mobile route. No web app manifest, no install prompt, no service
worker, no offline mode. No landscape-specific layout — the same rules apply
to a short wide screen, and if that reads badly it is its own change.
