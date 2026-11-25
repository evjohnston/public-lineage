---
version: 1
slug: "explorer-index-html"
primary_target: "explorer/index.html"
related_targets: []
---

# Lineage Explorer (explorer/index.html)

Scope: the whole local explorer app, including the overview (home) route. Visitor mode: Operate.
Audience and job: one researcher at a laptop beside a dark-themed notebook and DuckDB, looking up sociology lineages, tracing connections, reading the field as a network, and auditing and filling data gaps. 45.6k people, 38.9k advisor links, 12 curated schools, a 3D sociogram, institutions and a curation workflow.
Constraints: static HTML/JS, no build step, data precomputed to JSON; vendored libraries only; works offline.
Replaces: the Moreno-sociogram paper world, which the user found odd, hard to follow, overlapping and cluttered (too many tabs, crowded toolbars, wall-of-text panel, a home page with no story).
Unresolved: how much of the review queue (data/review/*.csv) the explorer should edit directly.

## Direction contract

THESIS: A graphite workbench of persistent panels: navigation, canvas, record and list each own a tile, divided by hairline seams, so nothing ever overlaps and every job has a fixed place. Refuses the floating-toolbar canvas with overlays stacked on the graph, and the white SaaS card dashboard.

OWN-WORLD: Graphite ground #16181d, panels #1b1e24, seams 1px #2c313a, text #e6e8eb / #a9b1bd. One accent blue #7aa2f7 for focus, selection and the traced path; amber #e0af68 for data notes and stamped states; red #f7768e only for errors and destructive actions. Category hues teal, violet, orange, validated on graphite. Source Sans 3 for words, Source Code Pro for every figure; panel headers in tiny tracked small caps; person names large.

STORY: Land on the overview, search or pick a starting person; the lineage fills the canvas, the record sits right in collapsible sections, the list strip below lists students or members; switch views from the left rail grouped Person / Field / Data with counts; trace a path in blue; open gaps and record a missing advisor.

FIRST VIEWPORT: 48px header (brand, search with / hint, field counts). Left rail 220px: Overview, then Person, Field, Data groups with counts, then Recent people. Centre: a title row (name, facts, segmented controls) over the canvas, a status row (legend, color key) beneath it, then a 200px list strip. Right panel 360px: record. Signature move: the record and list follow the canvas, so selecting anything updates all three tiles in place with a 150ms seam highlight.

FORM: Graphite workbench, dealt challenger 2 of 6 in a bolder re-roll (wins on both axes), seed:e393754ee5e74bb2.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
