"""Fill missing advisors from Wikidata for people we already know by Wikidata id.

fetch_wikidata.py keeps only pairs where one side is a sociologist. That drops the advisors of
many lineage roots, because early sociologists often trained under philosophers, economists or
historians. Here we start from people with no recorded advisor whose Wikidata id is known (it
came through a merged Wikidata link), ask Wikidata for their doctoral advisor (P184) in any field,
and repeat for those advisors, up to 4 generations up. No names are searched: every step follows
a Wikidata id, so nothing is guessed.

Outputs:
  data/external/wdanc_edges.parquet   same columns as wikidata_edges (source = "wikidata")
  data/external/wdanc_people.parquet  qid, name, birth_year, is_sociologist (advisors added here)
Advisors who are not sociologists on Wikidata (occupation sociologist or field sociology) are
flagged "outside the field" by export_explorer.py, like AFT's boundary advisors.

Usage: python -I scripts/fetch_wikidata_ancestors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_wikidata import chunks, qid, sparql, values, year  # noqa: E402  (same cache, pacing, User-Agent)
from merges import load_merges  # noqa: E402

EXT = ROOT / "data" / "external"
LEVELS = 4
LANGS = ["en", "fr", "de", "ru", "es", "it", "pl", "nl"]


def advisors_of(qids: list[str], level: int) -> list[dict]:
    rows = []
    for i, part in chunks(qids, 200):
        q = f"""SELECT ?s ?a (SAMPLE(?lab) AS ?label) (MIN(?b) AS ?birth)
                       (MAX(IF(BOUND(?soc), 1, 0)) AS ?isSoc) WHERE {{
          VALUES ?s {{ {values(part)} }}
          ?s wdt:P184 ?a .
          OPTIONAL {{ ?a rdfs:label ?lab . FILTER(LANG(?lab) = "en") }}
          OPTIONAL {{ ?a wdt:P569 ?b }}
          OPTIONAL {{ {{ ?a wdt:P106 wd:Q2306091 }} UNION {{ ?a wdt:P101 wd:Q21201 }} BIND(1 AS ?soc) }}
        }} GROUP BY ?s ?a"""
        rows += sparql(f"anc{level}_{i}", q)
    return rows


def labels(qids: list[str]) -> dict[str, str]:
    """Best label for items with no English one, in a fixed language order."""
    out = {}
    for i, part in chunks(qids, 200):
        q = f"""SELECT ?a ?lab (LANG(?lab) AS ?lang) WHERE {{
          VALUES ?a {{ {values(part)} }} ?a rdfs:label ?lab .
          FILTER(LANG(?lab) IN ({", ".join(f'"{l}"' for l in LANGS)})) }}"""
        best = {}
        for r in sparql(f"anclab_{i}", q):
            a, rank = qid(r["a"]), LANGS.index(r["lang"])
            if a not in best or rank < best[a][0]:
                best[a] = (rank, r["lab"])
        out |= {a: v[1] for a, v in best.items()}
    return out


def main() -> None:
    MERGE = load_merges()
    R = lambda p: MERGE.get(p, p)
    lin = json.loads((ROOT / "explorer" / "data" / "lineage.json").read_text())
    has_adv = {t for _m, t, *_ in lin["edges"]}
    soc = {r[0] for r in lin["people"] if not r[3] & 1}

    # Wikidata id and the exact name merge_external.py matched, for everyone in a merged Wikidata link
    we = pd.read_parquet(EXT / "wikidata_edges.parquet")
    name_of = dict(zip(we.advisor_qid, we.advisor_name)) | dict(zip(we.student_qid, we.student_name))
    pid_qid = {}
    for r in pd.read_parquet(EXT / "merged_edges.parquet").itertuples(index=False):
        if r.source == "wikidata" and "-" in str(r.source_id):
            aq, sq = str(r.source_id).split("-", 1)
            pid_qid[R(int(r.advisor_pid))] = aq
            pid_qid[R(int(r.student_pid))] = sq
    start = sorted({q for p, q in pid_qid.items() if p in soc and p not in has_adv})
    print(f"{len(start):,} people with no advisor and a known Wikidata id", flush=True)

    edges, people, frontier, seen = [], {}, start, set(start)
    for level in range(1, LEVELS + 1):
        if not frontier:
            break
        rows = advisors_of(frontier, level)
        nxt = []
        for r in rows:
            s, a = qid(r["s"]), qid(r["a"])
            people.setdefault(a, {"qid": a, "name": r.get("label"), "birth_year": year(r.get("birth")),
                                  "is_sociologist": r.get("isSoc") == "1"})
            edges.append((a, s))
            if a not in seen:
                seen.add(a); nxt.append(a)
        print(f"  generation {level}: {len(rows):,} advisor links, {len(nxt):,} new advisors", flush=True)
        frontier = nxt
    missing = [a for a, v in people.items() if not v["name"]]
    for a, lab in labels(missing).items():
        people[a]["name"] = lab
    for a in people:  # keep the name merge_external already matched for anyone it has seen
        if a in name_of:
            people[a]["name"] = name_of[a]

    def nm(q):
        return name_of.get(q) or (people.get(q) or {}).get("name")
    out = [{"source": "wikidata", "source_id": f"{a}-{s}", "advisor_name": nm(a), "student_name": nm(s),
            "advisor_qid": a, "student_qid": s, "year": pd.NA, "institution": None, "field": "ancestor",
            "url": f"https://www.wikidata.org/wiki/{s}", "via": "P184"}
           for a, s in dict.fromkeys(edges) if nm(a) and nm(s)]
    df = pd.DataFrame(out)
    if len(df):
        df["year"] = df["year"].astype("Int64")
    df.to_parquet(EXT / "wdanc_edges.parquet", index=False)
    pp = pd.DataFrame(people.values())
    if len(pp):
        pp["birth_year"] = pp["birth_year"].astype("Int64")
    pp.to_parquet(EXT / "wdanc_people.parquet", index=False)
    print(f"wrote {len(df):,} advisor links; {len(pp):,} advisors, {int(pp.is_sociologist.sum()) if len(pp) else 0:,} of them sociologists")


if __name__ == "__main__":
    main()
