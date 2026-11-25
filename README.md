# Academic lineage: sociology

A network of advisor–student ties among sociologists (about 45,000 people and 38,000 advisor links),
with a local explorer for lineages, academic kinship (siblings, cousins, "n times removed"),
co-authorship, schools of thought, institutions and placement, and time.

## Run the explorer

```sh
python3 -m http.server -d explorer 8765
# open http://localhost:8765/
```

The explorer is plain HTML/JS (Cytoscape.js, dagre, Leaflet, all vendored) and reads `explorer/data/*.json`.

## Rebuild the data

Raw downloads (`data/raw/`) and the DuckDB file are not in the repo. The fetch scripts in
`scripts/` recreate them; API keys go in `.env` (not committed). Then:

```sh
sh scripts/build_all.sh
```

The analysis write-up is in [docs/analysis/README.md](docs/analysis/README.md).

## Data sources and credits

- Academic Family Tree export (Zenodo 6349537, CC-BY-4.0). Liénard, J. F., Achakulvisut, T., Acuna, D. E., & David, S. V. (2018). Intellectual synthesis in mentorship determines success in academic careers. *Nature Communications*, 9, 4840.
- AFT-MAG training years (Zenodo 4917086). Ke, Q., Liénard, J., Acuna, D., & David, S. V. (2022).
- U.S. faculty hiring census (CC-BY-3.0-US). Wapman, K. H., Zhang, S., Clauset, A., & Larremore, D. B. (2022). Quantifying hierarchy and dynamics in US faculty hiring and retention. *Nature*, 610, 120–127.
- OpenAlex (CC0), ORCID public data (CC0), Wikidata (CC0), NSF Award API, theses.fr, HAL, and the open DSpace repositories of Minnesota, Illinois, Cornell, Oregon, Wisconsin and Chicago.
- Natural Earth land outlines (public domain).

Ties read from dissertation text are labelled unverified and carry the source passage.
