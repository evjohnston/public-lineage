#!/bin/sh
# Rebuild every derived dataset in the right order. Run from the project root.
set -e
PY=.venv/bin/python
$PY scripts/merge_external.py                      # match outside sources to AFT people
LINEAGE_NO_MERGES=1 $PY scripts/export_explorer.py  # unmerged export, so duplicates are visible
$PY -I scripts/resolve_duplicates.py               # decide merges -> person_merges.csv
$PY scripts/export_orcid.py                        # ORCID careers -> careers.json (feeds PhD years)
$PY scripts/export_explorer.py                     # final export with merges applied
$PY scripts/export_context.py                      # schools, communities, institutions
$PY scripts/export_coauthors.py                    # co-author network from OpenAlex
$PY -I scripts/analysis/run_analyses.py            # figures + results.json
