---
name: Lineage Explorer
description: Sociology's advisor-to-student network on a graphite workbench of fixed, seamed panels.
colors:
  accent: "#7aa2f7"
  accent-ink: "#0f1420"
  accent-wash: "rgba(122, 162, 247, 0.14)"
  note: "#e0af68"
  note-wash: "rgba(224, 175, 104, 0.10)"
  danger: "#f7768e"
  bg: "#16181d"
  panel: "#1b1e24"
  raise: "#23272f"
  seam: "#2c313a"
  seam-2: "#3b414c"
  text: "#e6e8eb"
  text-2: "#b3bac6"
  text-3: "#8f97a5"
  faint: "#4b5263"
  cat-teal: "#159a80"
  cat-violet: "#9a78ec"
  cat-orange: "#d9752a"
  cat-other: "#3b414c"
  edge: "#6b7280"
  cohort-1940: "#3d3424"
  cohort-1950: "#544629"
  cohort-1960: "#6d5a2e"
  cohort-1970: "#876f33"
  cohort-1980: "#a38639"
  cohort-1990: "#bf9d40"
  cohort-2000: "#d9b44c"
  cohort-2010: "#f0cc66"
typography:
  display:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tnum"
  body-strong:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 600
    lineHeight: 1.45
  small:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    letterSpacing: "0.09em"
  figure:
    fontFamily: "Source Code Pro, ui-monospace, Menlo, monospace"
    fontSize: "14.5px"
    fontWeight: 600
    lineHeight: 1.3
  figure-small:
    fontFamily: "Source Code Pro, ui-monospace, Menlo, monospace"
    fontSize: "11px"
    fontWeight: 500
rounded:
  hair: "3px"
  base: "5px"
  pill: "999px"
spacing:
  row: "6px"
  gap: "8px"
  inset: "10px"
  gutter: "16px"
  panel: "18px"
  sheet: "24px"
components:
  button:
    backgroundColor: "{colors.raise}"
    textColor: "{colors.text}"
    typography: "{typography.small}"
    rounded: "{rounded.base}"
    padding: "5px 11px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.base}"
    padding: "5px 11px"
  search-input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.base}"
    height: "32px"
    padding: "0 34px 0 32px"
  seg-button:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    typography: "{typography.small}"
    rounded: "{rounded.hair}"
    padding: "3px 10px"
  seg-button-pressed:
    backgroundColor: "{colors.raise}"
    textColor: "{colors.accent}"
  chip-toggle:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  chip-toggle-checked:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.text}"
  rail-link:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    rounded: "{rounded.base}"
    padding: "6px 10px"
  rail-link-current:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.text}"
  note:
    backgroundColor: "{colors.note-wash}"
    textColor: "{colors.note}"
    typography: "{typography.small}"
    rounded: "{rounded.base}"
    padding: "7px 10px"
  tag:
    backgroundColor: "transparent"
    textColor: "{colors.note}"
    typography: "{typography.label}"
    rounded: "{rounded.hair}"
    padding: "1px 6px"
  tile:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    padding: "14px 16px 16px"
  gap-tile-pressed:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.accent}"
---

# Design System: Lineage Explorer

## Overview

**Creative North Star: "The Graphite Workbench"**

The explorer is a dark-first developer console for a genealogy of scholars. Every job owns a fixed tile: header across the top, view rail on the left, the canvas in the centre with a title row above it and a status row and list strip beneath it, the record on the right. Tiles are divided by 1px seams, never by gaps, cards, or shadows, so the screen reads as one machined surface cut into compartments. Selecting anything updates canvas, record, and list in place; the record and strip acknowledge it with a 150ms seam flash.

Density is high and calm: small type, tabular figures, hairline rules between rows, one cool accent. Colour carries meaning only. Blue is the user's attention (focus, selection, the traced path); amber is the data's voice (notes, stamped states, cohort); the three category hues and the amber cohort ramp colour nodes on the canvas and nowhere else. The world rejects the floating-toolbar canvas with overlays stacked on the graph, and the white SaaS card dashboard.

**Key Characteristics:**
- Graphite ground with two lifted panel tones; depth by tone and seam, not shadow.
- One accent, rationed to state.
- Source Sans 3 for words, Source Code Pro for every figure.
- Panel and section headers in tiny tracked uppercase; person names large and bold.
- Controls live in the flow above or beside the canvas, never on top of it.

## Colors

A near-neutral graphite scale with a cool cast, one periwinkle accent, one amber data voice, and a reserved red.

### Primary
- **Workbench Blue** (accent): focus rings, selected rows and rail items, pressed segments, checked chips, the traced path on the canvas, the focus node, link hovers, primary buttons. Text set on it uses **Accent Ink**. **Accent Wash** is its 14% tint for selected backgrounds (rail current, selected table row, pressed gap tile, verdict box).

### Secondary
- **Ledger Amber** (note): data notes, stamped tags, data-health figures, education bars on the career timeline. **Note Wash** backs the note box, with a 28% amber border.

### Tertiary
- **Signal Red** (danger): declared for errors and destructive actions only. No shipping surface uses it yet.

### Neutral
- **Graphite** (bg): the page, the canvas, input and segmented-control wells, sticky table headers on sheets.
- **Panel Graphite** (panel): header, rail, toolbar, status row, list strip, record panel, overview tiles, popovers.
- **Raised Graphite** (raise): buttons, hover and pressed states.
- **Seam** (seam): every 1px divider between tiles and rows; the gap colour of seamed grids.
- **Seam Strong** (seam-2): control borders, table header rules, scrollbar thumbs.
- **Text** (text, 14:1 on bg), **Text Secondary** (text-2, 9:1), **Text Tertiary** (text-3, 6:1): primary copy, secondary copy and figures, labels and counts.
- **Faint** (faint): dropped marks on the canvas, link underlines, disabled kinship cells. Never body text.

### Canvas palette
- **Category hues** (cat-teal, cat-violet, cat-orange): the three pinnable slots when nodes are coloured by school, community or institution; everything else takes **Other** (cat-other). Validated for separation on graphite.
- **Cohort ramp** (cohort-1940 to cohort-2010): one amber hue, dim to bright by PhD decade. Sequential, never a rainbow.
- **Edge Grey** (edge): advisor edges and co-authorship curves; transcript and committee edges use Text Tertiary, dotted or dashed.
- Nodes are hollow Graphite discs with a Text ring; labels sit beneath in Source Sans 3 600 on an 85% Graphite text background.

### Named Rules
**The One Accent Rule.** Blue means "you are here or you chose this": focus, selection, traced path. It is never decoration, never a category, never a heading colour.

**The Amber Voice Rule.** Amber belongs to the data: notes, stamped states, health counts, cohort. A note is amber and upright, never italic.

**The Canvas-Only Hue Rule.** Category hues and the cohort ramp colour nodes and their key swatches only; chrome stays graphite and blue.

## Typography

**Body Font:** Source Sans 3 (with system-ui), self-hosted variable woff2 in `explorer/fonts`, roman and italic.
**Mono Font:** Source Code Pro (with ui-monospace, Menlo), self-hosted.

**Character:** A humanist sans for names and prose, paired with its sibling mono for counts, years and ranks, so figures line up like a console readout while names stay warm.

### Hierarchy
- **Display** (700, 34px, 1.05, -0.02em): the overview heading only; 28px under 900px.
- **Headline** (700, 24px, 1.15, -0.01em): the person's name in the record panel, sheet titles, notice headings.
- **Title** (700, 18px, 1.2): the toolbar title over the canvas; the title select.
- **Body** (400, 14.5px, 1.45, tabular numerals): base text. Strong (600) for names in lists and tables. Ledes cap at 75ch, findings at 70ch.
- **Small** (13px): secondary lines, controls, chips, buttons, key-value rows.
- **Label** (700, 11px, 0.08 to 0.09em tracking, uppercase, Text Tertiary): rail group headers, panel section headers, tile headers, table headers, segment labels, colour-key heading.
- **Figure** (Source Code Pro 600, 14.5px) and **Figure Small** (500, 11px): stat values, counts in rail and summaries, table numerics, gap-tile numbers (24px), kinship counts, timeline ticks.

### Named Rules
**The Figures-in-Mono Rule.** Every count, year, rank and statistic is set in Source Code Pro.

**The Names-Never-Mono Rule.** Person and institution names are always Source Sans 3, even inside a stat row (the text variant of a stat value switches back to the sans).

## Layout

A fixed application shell on a CSS grid: a 48px header row, a body row, and a credit footer. The body is a 208px rail plus a work area, which splits into a flexible stage and a 360px record panel (320px under 1180px). The stage stacks a toolbar (min 50px), the canvas (fills the rest), a status row (min 32px, single line, horizontal scroll), and a list strip (max 184px, sticky head). The overview and data sheets render inside the canvas as a scrolling sheet with 24px by 28px padding; the overview caps at 1180px.

Rhythm: 16px horizontal gutter on header, toolbar, status row and strip; 18px panel padding; rows at 5 to 7px vertical padding with a seam beneath; control gaps of 6 to 10px.

Under 900px the shell becomes one column: search wraps to its own line, the rail collapses behind a toggle, the canvas takes a fixed 62vh, the record panel follows below with a top seam, and grids drop to one column.

### Named Rules
**The Fixed Tile Rule.** Every job has a fixed tile. Controls, legends and lists sit in the flow beside the canvas; nothing floats over the drawing.

## Elevation & Depth

Flat and tonal. Depth comes from three ground tones (Graphite below, Panel above, Raised for controls) and 1px seams. Seamed grids (overview tiles, gap tiles, view links) set a 1px gap on a Seam background so the dividers are the grid itself. Shadows are reserved for transient layers detached from the shell.

### Shadow Vocabulary
- **Popover** (`box-shadow: 0 12px 32px rgba(0,0,0,0.45)`): search results and the menu dropdown.
- **Tooltip** (`box-shadow: 0 8px 20px rgba(0,0,0,0.4)` to `0 10px 24px rgba(0,0,0,0.45)`): map and 3D hover tips.
- **Seam flash** (`box-shadow: inset 0 0 0 1px` accent fading to transparent over 150ms): the record panel and strip acknowledging a selection.

### Named Rules
**The Seam-Not-Shadow Rule.** Tiles at rest never cast shadows; they are separated by a 1px seam.

## Shapes

One gentle radius (5px) on inputs, buttons, segmented wells, notes, popovers and seamed grid frames; 3px on small inner parts (segment buttons, tags, pins, kbd); full pills only for chip toggles and starter chips; circles for colour-key swatches, path step counters and nodes. Seams are always 1px. Disclosure carets are drawn as rotated 1.5px border corners; icons are inline 1.5 to 1.6px stroked SVG.

## Components

### Buttons
- **Shape:** gently rounded (5px).
- **Default:** Raised Graphite with a Seam Strong border, Text, 600 at 13px, 5px by 11px; hover lifts the border to Text Tertiary.
- **Primary:** Workbench Blue fill with Accent Ink text.
- **Disabled:** 45% opacity.
- **Text buttons:** "more" and stat-value buttons are underlined or blue mono, hover to accent.

### Segmented control
- **Style:** a Graphite well with a Seam Strong border and 2px inset; buttons 600 at 13px in Text Secondary.
- **Pressed:** Raised Graphite with accent text and an inset Seam Strong ring. Preceded by a Label.

### Chips
- **Toggle chip:** a real, focusable checkbox drawn as a pill with a 7px hollow dot; checked turns the border and dot accent over Accent Wash.
- **Starter chip:** a Raised pill with a mono count; hover sets an accent border.

### Menu dropdown
- A disclosure whose summary looks like a button, with an accent count badge; open sets an accent border. The popover is Panel Graphite with a Seam Strong border and the Popover shadow, holding toggle chips.

### Inputs / Fields
- **Style:** Graphite well (Panel inside the curate box), Seam Strong border, 5px radius, 30 to 32px tall (44px on the overview). Search carries a stroked magnifier and a `/` key hint.
- **Focus:** accent border plus a 1px accent ring; no outer glow.

### Navigation (rail)
- Labelled groups (Person, Field, Data, Recent) with tracked Label headers. Links are 500 Text Secondary with a 15px stroked icon and a right-aligned mono count; hover is Raised; current is Accent Wash with the count in accent. Recent people are 400 small, truncated.

### Record panel
- Name as Headline, institution in Text Tertiary beneath. Stat rows: label in small Text Secondary, value in Figure, seam between rows. Key-value rows on an 8.5rem label column. Collapsible sections use a Label-style summary with a rotating caret and a mono count, seamed above and below.

### Notes and tags
- **Note:** amber text on Note Wash with an amber hairline border, 5px radius, small size.
- **Tag:** amber uppercase 11px label in a 3px hairline amber box, for stamped states.

### Tables
- Full-width, collapsed borders, Label headers that sort (accent caret), seam under every row, numerics right-aligned in mono Text Secondary. Hover is Raised; selected is Accent Wash with the name in accent. Headers are sticky on Graphite (Panel inside the strip).

### Gap tiles and overview tiles
- Seamed grids of Panel Graphite tiles. A gap tile pairs a 24px mono figure with a 600 label and a Text Tertiary reason; pressed turns figure and label accent over Accent Wash. Overview tiles carry a Label header with an accent "see all" link, then seamed rows (school bars in accent at 85%, people with mono counts, health rows with amber figures).

### Graph canvas (signature)
- Hollow nodes ringed in Text, labels beneath, Edge Grey arrows. Out-of-field people are dashed and secondary; dropped context drops to Faint rings. The traced path thickens to 3.6px accent edges with accent rings and filled endpoints. The status row beneath carries the legend glyphs and colour key with mono counts and pin toggles.

## Do's and Don'ts

### Do:
- **Do** divide every tile and row with a 1px Seam; build grids as 1px gaps over a Seam ground.
- **Do** reserve Workbench Blue for focus, selection and the traced path, with Accent Ink for text on it.
- **Do** set every figure in Source Code Pro and every name in Source Sans 3.
- **Do** put data notes and stamped states in amber, upright, on Note Wash.
- **Do** keep canvas controls, legends and lists in the toolbar, status row and strip.
- **Do** colour nodes only from the three category hues, Other, or the amber cohort ramp.

### Don't:
- **Don't** float toolbars, legends or overlays on the graph canvas.
- **Don't** give resting tiles shadows or turn the shell into white SaaS cards.
- **Don't** use the accent as decoration, a category, or a heading colour.
- **Don't** italicise notes or set names in mono.
- **Don't** use Faint for readable text.
- **Don't** introduce a rainbow for the cohort ramp; it stays one amber hue.
