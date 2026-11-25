---
name: Lineage Explorer
description: Sociology's advisor-to-student network drawn as an ink sociogram on white paper.
colors:
  red: "#c8102e"
  red-wash: "#fbeaec"
  blue: "#1f4e9c"
  blue-wash: "#edf2fa"
  ink: "#161616"
  ink-2: "#4a4a48"
  ink-3: "#6a6a67"
  ink-faint: "#c9c6be"
  rule: "#e9e6df"
  wash: "#f6f4ef"
  paper: "#ffffff"
typography:
  headline:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "1.625rem"
    fontWeight: 700
    lineHeight: 1.15
  title:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.45
    fontFeature: "tnum"
  body:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tnum"
  body-strong:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.45
  small:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.45
    letterSpacing: "0.06em"
  graph-label:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.2
rounded:
  none: "0px"
  circle: "50%"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "18px"
  xl: "22px"
components:
  tab:
    textColor: "{colors.ink-2}"
    typography: "{typography.body-strong}"
    height: "56px"
  tab-active:
    textColor: "{colors.ink}"
    typography: "{typography.body-strong}"
  search-input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "0 10px 0 32px"
    height: "34px"
  segmented-option:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.none}"
    padding: "4px 11px"
  segmented-option-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  button:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body-strong}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
  button-hover:
    backgroundColor: "{colors.wash}"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
  chip:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "5px 12px"
  data-note:
    backgroundColor: "{colors.blue-wash}"
    textColor: "{colors.blue}"
    padding: "6px 10px"
  verdict:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.red}"
    padding: "10px 12px"
  path-step-marker:
    textColor: "{colors.red}"
    rounded: "{rounded.circle}"
    size: "18px"
  table-row-selected:
    backgroundColor: "{colors.red-wash}"
  side-panel:
    backgroundColor: "{colors.paper}"
    padding: "22px"
    width: "360px"
---

# Design System: Lineage Explorer

## Overview

**Creative North Star: "The Moreno Sociogram"**

The explorer draws sociology's academic genealogy the way Jacob Moreno drew the field's first networks: ink circles, arrows and typed labels on white paper. Everything is ink on paper. Two pencils mark the page: a red one for whatever the researcher is tracing or acting on, and a blue one for notes about the data. The result reads like a working document the researcher can trust and audit, not a dashboard performing for an audience.

Density is high and calm. One sans face in four weights carries every role, numerals are tabular everywhere, and regions are divided by 1.5px ink rules, not by cards or shadows. The diagram, the record panel and the ranked tables share one material: hollow and filled circles, straight arrows, thin warm rules between rows.

The build rejects the dark neon force-graph hairball and the gray-blue SaaS graph explorer. Neither aesthetic belongs here.

**Key Characteristics:**
- White paper ground, near-black ink, 1.5px strokes for every structural line.
- Red pencil only for the traced path, focus and the active choice; blue pencil only for data-quality notes, always italic.
- Circle grammar: hollow = sociology, dashed = outside the field, filled ink = the person in focus.
- Square corners everywhere except the circles themselves.
- Flat. No shadows, no rounded panels, no gradients.

## Colors

An ink-on-paper palette with two pencils. Neutrals do almost all the work.

### Primary
- **Red Pencil** (`red`): The one thing being traced or acted on. The Connect path's thick stroke and arrowheads, path-node borders, the active tab underline, focus outlines, the sort caret, numbered path-step markers, the verdict box, the selected data-gap category, link hover, and the text caret.
- **Red Wash** (`red-wash`): The selected table row and text selection. The only red fill larger than a mark.

### Secondary
- **Blue Pencil** (`blue`): Data-quality notes only: panel flags, gap-category explanations, Connect's distance note, and notes on empty states. Always set in italic.
- **Blue Wash** (`blue-wash`): The tinted ground behind a panel data note.

### Neutral
- **Ink** (`ink`): Body text, every 1.5px rule and border, node outlines and edges, the filled focus node, the pressed segmented option and the primary button.
- **Secondary Ink** (`ink-2`): Institutions, sub-lines, inactive tabs, out-of-field node labels, legend text. 9:1 on paper.
- **Tertiary Ink** (`ink-3`): Counts, section labels, table headers, the credit line, placeholders. 5.3:1 on paper; the floor for any text.
- **Faint Ink** (`ink-faint`): Underline color on clickable stat numbers and scrollbar thumbs. Not for text.
- **Warm Rule** (`rule`): Hairline (1px) dividers between stat rows, list rows, table rows and under the toolbar.
- **Wash** (`wash`): Hover tint for rows, results, buttons and chips.
- **Paper** (`paper`): The page, the panel, inputs and buttons. No other surface color exists.

### Named Rules
**The Two Pencils Rule.** Red means "the thing you are tracing or acting on"; blue means "a note about the data". Never use either for decoration, branding or category coding.

**The Drop-to-Light-Ink Rule.** When a path is traced, every mark not on it drops to 32% opacity instead of changing color, so the red path is the only saturated thing on the page.

## Typography

**Body Font:** Source Sans 3 (self-hosted variable woff2, 200 to 900, with roman and italic; fallback system-ui, sans-serif)

**Character:** One humanist sans in four weights reads like a typed label on a research diagram. Hierarchy comes from weight and a short size ramp, not from a second family.

### Hierarchy
- **Headline** (700, 1.625rem, 1.1 to 1.15): Panel person names, sheet titles, the canvas toolbar title, notice headings, and the big numbers in the data-gap grid.
- **Title** (700, 1.125rem): The brand wordmark and stat-row values.
- **Body** (400, 0.9375rem, 1.45): All running text and table cells. Ledes cap at 75ch, notices at 52ch.
- **Body Strong** (600, 0.9375rem): Person names in lists, results and tables; tabs; buttons; chips.
- **Small** (400 or 600, 0.8125rem): Counts, sub-lines, legend, segmented options, relation lines under path steps.
- **Label** (700, 0.75rem, 0.06em, uppercase, Tertiary Ink): Section labels inside the panel that name the list below them (Advisors, Students, Path) and table column headers. A label names its own content; it never sits above a headline.
- **Graph Label** (600, 13px; focus 700, 15px; out-of-field 400 in Secondary Ink): Node names under circles on a semi-opaque paper backing, with a second line carrying the descendant count.

### Named Rules
**The Tabular Rule.** `font-variant-numeric: tabular-nums` is set on the body; every number lines up in columns without per-element opt-in.

**The Italic Is Blue Rule.** Italic is reserved for blue-pencil data notes (and the dotted "more" stub in the diagram). Do not use italic for emphasis elsewhere.

## Layout

A fixed application frame on a three-row grid: a 56px top bar, a work area that fills the viewport, and a one-line credit footer. The work area splits into a fluid canvas or sheet on the left and a fixed 360px record panel on the right, divided by a 1.5px ink rule.

- **Top bar:** brand, search (min(360px, 34vw)) and four text tabs in one row, 22px side padding, 28px gaps, ruled below in ink.
- **Canvas:** the diagram fills the stage; a toolbar overlays its top edge on 95% white with a hairline rule below; the legend sits bottom-left at 18px.
- **Sheet:** tables and the gap grid scroll inside the stage with 22px by 26px padding.
- **Panel:** 22px padding; sections separated by 22px above each label.
- **Rhythm:** 6, 8, 12, 18 and 22px recur. Rows run 5 to 7px vertical padding, so lists stay dense.
- **Responsive:** at 960px and below, the top bar wraps (search drops to its own full-width row), the work area stacks with the canvas at minmax(440px, 62vh) above the panel, the panel's divider moves to its top edge, and the toolbar becomes static. At 560px and below, the brand subtitle and legend hide and the Connect pickers go full width.

**The Ruled Regions Rule.** Regions are separated by 1.5px ink lines and rows by 1px warm rules. Never separate regions with background tints, cards or gaps alone.

## Elevation & Depth

Completely flat. There are no shadows anywhere in the system. Depth is carried by line weight (1.5px ink for structure, 1px warm rule for rows) and, on the canvas, by opacity: overlays (toolbar, legend, checkboxes) sit on 86 to 95% white so diagram marks read faintly beneath them. The only `box-shadow` declarations in the build are lines, not shadows: the red 3px inset underline on the active tab and a 1px red ring that thickens an input's border on focus.

**The Flat Paper Rule.** Nothing floats. If a surface needs separation, rule it in ink.

## Shapes

Square corners on every rectangle: inputs, buttons, chips, segmented controls, the results dropdown, the verdict box and data notes all have a 0px radius. The circle is the system's only curve, and it is semantic: node circles in the diagram, the 12px circle markers in person lists, the legend, and the 18px numbered path-step rings. Stroke style carries meaning: solid = sociology, dashed = outside the field (and postdoc edges), dotted = a collapsed "more" stub.

**The Circle Means a Person Rule.** Circles stand for people or for steps along a lineage. Do not use circles, pills or rounded corners for controls or containers.

## Components

### Top Bar Tabs
- **Style:** text-only links in Body Strong, Secondary Ink, filling the bar's full height.
- **Hover:** shifts to Ink.
- **Active:** Ink text with a 3px red underline flush to the bar's bottom rule (`aria-current="page"`), transitioned over 200ms.

### Search Combobox
- **Input:** 34px tall, 1.5px ink border, square, inline 16px stroked magnifier at left.
- **Focus:** border turns red and thickens with a 1px red ring; the caret is red.
- **Results:** a square listbox ruled in ink, at least 420px wide; each row shows the name (Body Strong), institution (Small, Tertiary Ink) and a right-aligned count. The highlighted row gets Wash and a red name.

### Segmented Control
- **Style:** a 1.5px ink frame holding Small 600 options divided by 1px ink lines, with an optional Small label beside it.
- **Hover:** Wash. **Pressed:** solid Ink with Paper text.

### Buttons and Chips
- **Button:** 1.5px ink border, Paper fill, Body Strong, 6px by 12px, optional 14px stroked SVG icon. Hover: Wash.
- **Primary Button:** solid Ink with Paper text.
- **Chip:** the same frame at 5px by 12px, used for starting suggestions on empty states, with an optional Small count in Tertiary Ink.

### Ruled Stat Rows
- A label on the left and a Title-weight number on the right, baseline-aligned, between 1px warm rules. Clickable numbers are underlined in Faint Ink and turn red on hover.

### Person Lists
- Rows ruled in warm hairlines, each with a 12px stroked circle marker (dashed for outside the field), the name in Body Strong (ellipsized), and a Small count at right. Hover turns the name red and underlines it. A "show more" text button in Small, Secondary Ink, ends long lists.

### Blue-Pencil Data Note
- Italic Blue Pencil text on Blue Wash, 6px by 10px, square. It flags missing or suspect data and is the only tinted block in the panel.

### Red Verdict Box
- A 1.5px red frame on Paper around the Connect answer, with the two names in bold Ink and the relation in red.

### Numbered Path Steps
- An ordered list whose markers are 18px red rings with 11px bold red numerals, each step ruled below, with a Small relation line ("advised the next person") under the name.

### Data Tables
- Header cells in Label style, ruled below in 1.5px ink and sticky; sort buttons span each header, and the sorted column shows a 12px red stroked SVG caret. Rows are ruled in warm hairlines, hover to Wash, and the selected row fills with Red Wash. Numeric columns are right-aligned; rank and institution recede to Tertiary and Secondary Ink.

### Data-Gap Category Grid
- An auto-fill grid (min 260px columns) under a 1.5px ink rule. Each cell pairs a right-aligned Headline count with a Body Strong label and an italic Blue Pencil explanation. Hover or pressed turns the label red; pressed turns the count red too.

### Lineage Diagram (signature)
- Top-to-bottom layered tree (dagre). Nodes are circles sized by descendants (20px plus 6 per log10 step), Paper fill, 1.5px ink border; out-of-field nodes are dashed with lighter labels; the focus node is filled Ink. Edges are straight 1.3px ink lines with triangle arrowheads at 85% opacity, dashed for postdocs. Hover gives a node a 2.5px red border.
- **Traced path:** path edges become 3.6px red strokes with larger arrowheads drawn above everything; path nodes get 3px red borders, endpoints fill red; all other marks drop to 32% opacity.
- **Motion:** 200ms ease-out (cubic-bezier(0.16, 1, 0.3, 1)) fades on recenter and on opacity, color and width changes. Disabled under reduced motion.

## Do's and Don'ts

### Do:
- **Do** draw every structural line at 1.5px in Ink and every row divider at 1px in Warm Rule.
- **Do** keep red for the traced path, focus and the active selection, and blue for data notes in italic.
- **Do** keep the circle grammar: hollow for sociology, dashed for outside the field, filled ink for the person in focus.
- **Do** use Source Sans 3 for every role, with tabular numerals.
- **Do** keep text at Tertiary Ink (5.3:1) or darker; Faint Ink is for marks, never text.
- **Do** use stroked inline SVG for icons, carets and markers, inheriting ink or red.

### Don't:
- **Don't** add shadows, rounded panels, cards or gradients.
- **Don't** use a dark or neon graph canvas, or gray-blue SaaS chrome.
- **Don't** use red or blue for decoration, category color or branding.
- **Don't** introduce a second typeface or a display face.
- **Don't** put uppercase labels above headlines as eyebrows; the label style only names the list or column directly beneath it.
