"""Which field the pipeline is building, and where that field's files live.

Set LINEAGE_FIELD (default "sociology"). Sociology keeps the original layout; any other field
gets its own working tree so the two never overwrite each other:

                 sociology                 other fields (e.g. physics)
  WORK/data      data/                     fields/<field>/data/
  EXPL           explorer/data/            explorer/data/<field>/
  DOCS           docs/analysis/            docs/analysis/<field>/

Raw downloads (data/raw/: the AFT export, AFT-MAG, Wikidata query cache) are shared.
The aft_people column is still called in_sociology for every field; it means "in this field".
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELD = os.environ.get("LINEAGE_FIELD", "sociology")

FIELDS = {
    "sociology": {
        "label": "Sociology", "noun": "sociologist", "nouns": "sociologists",
        "aft_tag": "sociology",
        "wd_occ": "Q2306091", "wd_field": "Q21201",          # sociologist; sociology
        "hiring": "Sociology",                                # Wapman et al. 2022 field name
        "orcid_re": rb"sociolog|soziolog|socjolog",
    },
    "physics": {
        "label": "Physics", "noun": "physicist", "nouns": "physicists",
        "aft_tag": "physics",
        "wd_occ": "Q169470", "wd_field": "Q413",              # physicist; physics
        "hiring": "Physics",
        "orcid_re": rb"physic|physik|fisica|physique",
    },
}
if FIELD not in FIELDS:
    raise SystemExit(f"unknown LINEAGE_FIELD {FIELD!r}; known: {', '.join(FIELDS)}")
CFG = FIELDS[FIELD]

if FIELD == "sociology":
    WORK, EXPL, DOCS = ROOT, ROOT / "explorer" / "data", ROOT / "docs" / "analysis"
    AUTHORPUB = ROOT / "data" / "raw" / "aft" / "authorpub_soc.parquet"
else:
    WORK, EXPL, DOCS = ROOT / "fields" / FIELD, ROOT / "explorer" / "data" / FIELD, ROOT / "docs" / "analysis" / FIELD
    AUTHORPUB = WORK / "data" / "authorpub.parquet"
for d in (WORK / "data" / "external", WORK / "data" / "review", EXPL, DOCS / "figs"):
    d.mkdir(parents=True, exist_ok=True)
