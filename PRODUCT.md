# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
Static HTML/CSS/JS with no build step, served locally (`python -m http.server`). Cytoscape.js (+ dagre layout) for lineage trees. Data is precomputed in Python from `data/lineage.duckdb` and shipped as JSON. Chosen by the user from a recommendation; local only for now, portable to static hosting later.

## Users
The project owner, a researcher studying the academic genealogy of sociology. They use the explorer alongside the analysis to look up lineages, test hunches and audit the data. No public audience yet.

## Product Purpose
An exploration tool for the sociology advisor→student network: see a person's academic ancestors and descendants, find how two sociologists are connected, survey the largest academic families, and see where the data is thin or suspect. Success means the researcher trusts what they see, or can tell exactly where not to.

## Positioning
Unlike academictree.org's per-person pages, it treats the field as one network: dynasties, paths between people and data gaps are computed across the whole graph, with OpenAlex details added as matching completes.

## Operating Context
Used on a laptop next to Python/DuckDB analysis. Data source: Academic Family Tree Zenodo export (snapshot 2022-03-12, CC-BY-4.0; cite Liénard et al. 2018, Nature Communications 9:4840), filtered to people tagged sociology plus their out-of-field advisors and students.

## Capabilities and Constraints
- v1 jobs: person lineage (ancestors/descendants tree, click to recenter), connect two people (shared ancestor / shortest lineage path), dynasty overview (largest families, most students, deepest chains), data quality flags.
- Graph: ~27k people, ~21k mentorship edges (99% PhD advising), no cycles, 5,454 separate clusters (largest 3,734), 643 people with multiple advisors.
- Known data issues: Ed.D.-style doctorates tagged sociology (e.g., Capella, La Verne), people with no recorded advisor, data ends 2022.
- OpenAlex matching (works, topics, citations) is in progress; the UI must work without it.

## Evidence on Hand
Real data only: `data/lineage.duckdb` (tables aft_people, aft_mentorship, aft_collab, aft_affiliation, aft_locations). No user testimonials or external claims.

## Product Principles
1. Show the data truthfully: surface uncertainty and gaps instead of hiding them.
2. Optimize for the researcher's speed and density, not first-visit onboarding.
3. Every view should lead somewhere else: people, institutions and paths are all clickable.
4. Keep attribution to the Academic Family Tree visible.
