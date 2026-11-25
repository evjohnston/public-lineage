---
version: 1
slug: "explorer-index-html"
primary_target: "explorer/index.html"
related_targets: []
---

# Lineage Explorer (explorer/index.html)

Scope: the whole local explorer app. Visitor mode: Operate.
Audience and job: one researcher, at a laptop beside their DuckDB analysis, looking up sociology lineages, tracing connections, surveying dynasties and auditing data gaps.
Constraints: static HTML/JS, no build step, data precomputed to JSON; must work before OpenAlex matching lands.
Home route: reopens the last-viewed lineage, so the first viewport is a tree; only a first visit shows the starter screen, an Operate empty state that teaches the tool with real starting lineages.
Unresolved: how OpenAlex fields (topics, citations) join the person panel.

## Direction contract

THESIS: Draw the lineage the way Moreno drew sociology's first networks: ink circles, arrows and typed labels on white, with red pencil kept for the one thing the researcher is tracing. Refuses the dark neon force-graph hairball and the gray-blue SaaS graph explorer.

OWN-WORLD: White paper ground, ink #161616 at 1.5px strokes, red pencil #c8102e only for the active path and focus, blue pencil #1f4e9c only for data-quality notes written in italic, warm rule #e9e6df. Source Sans 3 throughout, tabular numerals. Hollow circle = sociology, dashed circle = outside the field, filled ink = focused person. 1.5px ink rules divide regions; no shadows, no rounded panels.

STORY: Search a name, see ancestors above and descendants below by generation, click any person to recenter; open Connect to trace two people's path in red; scan Dynasties ranked by descendants and students; open Data gaps to see what is missing, flagged in blue.

FIRST VIEWPORT: 56px top bar with name, search and four tabs (Lineage, Connect, Dynasties, Data gaps; red underline on the active tab). Canvas fills the left with a top-to-bottom layered tree, focus filled ink; legend bottom-left. A 360px panel on the right, ruled in ink, holds name, institution, tabular counts, clickable advisor and student lists, and blue flags.

FORM: Moreno sociogram, grounded candidate 1 of 7 (chosen as the pick card), seed:b5b3f77e7f5a6400. Signature move: the red pencil path; when Connect traces two people, their path redraws as a thick red stroke with arrowheads while every other mark drops to light ink. Motion: 200ms ease-out fades on recenter only.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
