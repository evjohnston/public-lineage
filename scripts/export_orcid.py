"""Attach ORCID careers (education and employment) to people in the lineage data.

Inputs: data/external/orcid_affiliations.parquet (scripts/extract_orcid_summaries.py) and the ways
we know a person's ORCID iD. Each person gets the iD by the first route that works:
  aft       the ORCID on their Academic Family Tree record
  wikidata  Wikidata lists the iD (joined via the Wikidata person behind a merged link)
  openalex  their matched OpenAlex author record lists the iD
  name      ORCID name equals a unique full name here AND an affiliation shares a distinctive
            institution word with the person's recorded institution (weakest; labelled)

Output: explorer/data/careers.json
  {pid: [orcid, basis, [[kind, organization, department, role, start_year, end_year], ...]]}
Usage: python scripts/export_orcid.py
"""

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
EXT = WORK / "data" / "external"
OUT = EXPL / "careers.json"
sys.path.insert(0, str(Path(__file__).parent))
from merges import load_merges  # noqa: E402

ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")
STOP = {"university", "of", "the", "at", "college", "and", "state", "institute", "de", "la", "du", "school", "new",
        "universite", "universidad", "universita", "department", "sociology", "faculty", "center", "centre"}


def norm(s):
    s = unicodedata.normalize("NFKD", s if isinstance(s, str) else "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z]+", " ", s).strip()


def words(s):
    return {w for w in norm(s).split() if w not in STOP and len(w) > 2}


def main():
    R = (lambda m: lambda p: m.get(p, p))(load_merges())
    if not (EXT / "orcid_affiliations.parquet").exists():  # no ORCID records fetched for this field yet
        OUT.write_text("{}"); print("no orcid_affiliations.parquet; wrote empty", OUT); return
    aff = pd.read_parquet(EXT / "orcid_affiliations.parquet")
    lin = json.loads((EXPL / "lineage.json").read_text())
    people = {r[0]: r for r in lin["people"]}

    pid_of, basis = {}, {}
    con = duckdb.connect(str(WORK / "data" / "lineage.duckdb"), read_only=True)
    for pid, v in con.execute("SELECT pid, orcid_id FROM aft_people WHERE orcid_id IS NOT NULL").fetchall():
        for o in ORCID_RE.findall(v):
            pid_of.setdefault(o, R(pid)); basis.setdefault(o, "aft")
    if (EXT / "wikidata_people.parquet").exists() and (EXT / "merged_edges.parquet").exists():
        wp = pd.read_parquet(EXT / "wikidata_people.parquet")
        q_orcid = {r.qid: ORCID_RE.findall(str(r.orcid)) for r in wp.itertuples() if isinstance(r.orcid, str)}
        for r in pd.read_parquet(EXT / "merged_edges.parquet").query("source == 'wikidata'").itertuples():
            aq, _, sq = str(r.source_id).partition("-")
            for pid, q in ((R(int(r.advisor_pid)), aq), (R(int(r.student_pid)), sq)):
                for o in q_orcid.get(q, []):
                    pid_of.setdefault(o, pid); basis.setdefault(o, "wikidata")
    oa = EXT / "openalex_authors.parquet"
    if oa.exists():
        a = pd.read_parquet(oa)
        a = a[a.orcid.notna()] if "orcid" in a else a.iloc[0:0]
        match = dict(con.execute("SELECT openalex_id, pid FROM oa_author_match WHERE confidence IN ('high','medium')").fetchall())
        for r in a.itertuples():
            if r.openalex_id in match:
                pid_of.setdefault(r.orcid, R(match[r.openalex_id])); basis.setdefault(r.orcid, "openalex")

    # name + institution, for ORCID records not reached by an identifier
    full = defaultdict(set)
    for pid, r in people.items():
        t = norm(r[1]).split()
        if len(t) >= 2:
            full[f"{t[0]} {t[-1]}"].add(pid)
    unique = {k: next(iter(v)) for k, v in full.items() if len(v) == 1}
    taken = set(pid_of.values())
    by_orcid = aff.groupby("orcid")
    for o, g in by_orcid:
        if o in pid_of:
            continue
        t = (norm(g.given_names.iloc[0]) + " " + norm(g.family_name.iloc[0])).split()
        if len(t) < 2:
            continue
        pid = unique.get(f"{t[0]} {t[-1]}")
        if pid is None or pid in taken:
            continue
        inst = words(people[pid][2])
        if inst and any(inst & words(org) for org in g.organization):
            pid_of[o], basis[o] = pid, "name"
            taken.add(pid)

    out = {}
    for o, g in by_orcid:
        pid = pid_of.get(o)
        if pid is None or pid not in people:
            continue
        items = g.sort_values(["start_year"], na_position="last")
        sv = lambda v: v if isinstance(v, str) else None  # pandas NaN -> null
        out[str(pid)] = [o, basis[o], [[r.kind, sv(r.organization), sv(r.department), sv(r.role),
                                         None if pd.isna(r.start_year) else int(r.start_year),
                                         None if pd.isna(r.end_year) else int(r.end_year)] for r in items.itertuples()][:40]]
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    counts = pd.Series([v[1] for v in out.values()]).value_counts().to_dict()
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB): {len(out):,} people with ORCID careers", counts)


if __name__ == "__main__":
    main()
