# Floating-panel shell

Date: 2026-07-19

## Problem

The console reads as a boxed dashboard rather than a situational-awareness surface. The
map is confined to a 70% column of a `react-resizable-panels` group, the card deck fills
the remaining 30% edge to edge, and a drag handle sits between them. Nothing floats,
nothing overlaps, and the map — the product's main object — never fills the screen.

The reference the design is measured against (a dark map application with floating rounded
panels above a full-bleed basemap) gets its character from three things: the map bleeds to
every edge, panels hover above it as discrete cards with margin and shadow, and controls
are small round floating buttons rather than chrome.

Colour is not the gap. `app/globals.css` already carries a cool blue-black console palette,
a single `signal` accent and a semantic severity scale from WS1 of #269. The gap is layout
language.

## Goals

- The map fills the viewport, edge to edge, beneath everything else.
- Deck and detail float above it as visually identical cards.
- The map can be revealed: the deck collapses and restores.
- One shared surface component so panels cannot drift apart visually.

## Non-goals

- **Basemap restyling.** The reference's calm comes partly from a desaturated basemap, but
  changing the OpenFreeMap style risks the missing-sprite reload loop fixed in #407/#408.
  Separate issue.
- **Photography.** The reference leans on image grids and per-row thumbnails. OSINT event
  data carries no imagery; imitating that would produce empty rectangles.
- **Detail-card anatomy.** Rewriting the pop-out into icon-led metadata rows and sectioned
  content is a separate piece of work.
- **New dependencies.**

## Design

### The stage

`SplitLayout` stops composing `Panel` / `PanelGroup` / `PanelResizeHandle` and becomes a
layered stage:

| layer | placement | z |
| --- | --- | --- |
| `MapPane` | `absolute inset-0` | 0 |
| Filter rail | floating, docked right (an overlay inside `MapPane`) | 20 |
| Deck | `top-3 left-3 bottom-3`, width `clamp(320px, 28vw, 460px)` | 30 |
| Detail card | floats immediately right of the deck, same width and insets | 30 |
| Collapse tab | rides the outer edge of whichever panels are showing | 30 |

Panels are docked **left**, matching the reference image: the deck first, the detail
opening to its right, map filling everything beyond them. The filter rail moves to the
right edge, since the left now belongs to the panels.

The stage publishes a `--panel-width` custom property carrying the *total* width occupied
by floating panels — one panel width normally, two plus the gap when the detail is open,
zero when the deck is collapsed. Map-level overlays (the time scrubber, the collapse tab)
offset from it, so nothing slides underneath a panel and nothing needs to measure the DOM.

The collapse handle is an outer tab rather than a button inside the deck: the deck's header
row already carries the card title on the left and the expand control on the right.

Panel width becomes a shared constant rather than resizable. `StoryDetailCard` currently
positions itself using `deckWidthPx`, captured from the resizable panel's `onResize`; with a
fixed width that plumbing collapses into a constant and the overlay hack disappears.

**Accepted trade:** drag-to-resize is lost. The reference has fixed panel widths, and the
resize handle is a principal reason the current layout reads as boxed. `react-resizable-panels`
is used in `SplitLayout` and nowhere else, so the dependency is removed with it.

### `FloatingPanel`

A new component owning exactly one concern: the floating surface. Rounded corners, hairline
border, translucent background with backdrop blur, shadow, clipped overflow. Deck, detail
and any later panel wrap in it.

It takes children and optional class overrides. It holds no state and knows nothing about
what it contains, so it can be reasoned about and restyled in isolation — which is the point,
since consistent surfaces are what make separate panels read as one product.

`CardDeck` internals are untouched.

### Collapse

The deck collapses to a tab on the outer edge of the panels; clicking the tab or pressing `]`
restores it. `]` already toggles a rail in the current keyboard handler and is repurposed,
since the right rail it used to toggle went with the globe in #494.

State is local to `SplitLayout`. No store, no persistence: a collapsed deck is a transient
"let me see the map" gesture, not a preference.

### Narrow screens

The existing `isNarrow` two-tab switch is kept. Below 900px the deck renders as a floating
sheet over the map instead of a full-width column. No new responsive system.

## Verification

The frontend has no component-test infrastructure — every suite under `__tests__` tests pure
library functions. A layout change of this kind cannot be honestly verified by a passing
build, so:

- `tsc --noEmit`, `pnpm lint`, `pnpm test` and `pnpm build` must all pass.
- Screenshots of the running app (deck open, deck collapsed, detail open) are captured and
  attached to the pull request. **Not achieved:** no browser automation is available on
  this machine, so the layout ships unverified and the first revision reached the user with
  a runtime crash — a `NavigationControl` rendered outside `<MapGL>`, where the map context
  is null. Zoom controls were dropped rather than re-placed blind.
- The map must remain interactive beneath the panels: pan, zoom, marker click, country
  click, and cluster drill-in all still work with panels floating over them.

A passing build is necessary, not sufficient. The screenshots are the evidence.
