#!/bin/sh
# Build a field other than sociology (its files go to fields/<field>/, explorer/data/<field>/ and
# docs/analysis/<field>/). Run from the project root:
#   LINEAGE_FIELD=physics sh scripts/build_field.sh --fetch   # first time: pull every source
#   LINEAGE_FIELD=physics sh scripts/build_field.sh           # later: rebuild from what is cached
# Field settings (AFT tag, Wikidata ids, census name) live in scripts/field.py.
set -e
: "${LINEAGE_FIELD:?set LINEAGE_FIELD, e.g. LINEAGE_FIELD=physics}"
export LINEAGE_FIELD
PY=.venv/bin/python
if [ "$1" = "--fetch" ]; then
  $PY scripts/build_aft_sociology.py                 # the field's slice of the Academic Family Tree
  $PY scripts/fetch_wikidata.py                      # doctoral advisor links (P184/P185) for the field
  $PY scripts/fetch_aft_authorpub.py                 # AFT person -> DOI links (local copies of authorPub)
  $PY scripts/match_openalex.py works                # OpenAlex authorships for those DOIs
  $PY scripts/match_openalex.py vote                 # person -> OpenAlex author
  $PY scripts/fetch_openalex_authors.py              # author profiles: topics, first year, ORCID
  $PY -I scripts/fetch_orcid_api.py                  # ORCID education records (PhD years)
  $PY scripts/fetch_faculty_hiring.py                # Wapman et al. 2022, this field's slice
  $PY scripts/match_hiring_institutions.py           # census institutions -> AFT locations
fi
sh scripts/build_all.sh
if [ "$1" = "--fetch" ]; then
  $PY scripts/fetch_wikidata_ancestors.py            # advisors of known roots (needs lineage.json)
  sh scripts/build_all.sh
fi
