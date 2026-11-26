"""Find Wikidata doctoral advisors for unlinked roots by name, for human review.

fetch_wikidata_ancestors.py only follows people whose Wikidata id we already know. Many roots of the
tree (people with students but no advisor) are on Wikidata but were never linked. Here we look up
the top roots by exact name (full name, and first + last), keep only those that match exactly one
human who has a doctoral advisor (P184), and check the match against what we know:
  birth_ok  their birth year fits our PhD year (or estimate)
  inst_ok   a Wikidata employer or school shares a word with our institution
Nothing is merged. Rows go to data/review/wikidata_name_matches.csv with a suggestion; mark the
accept column "yes" for the ones you agree with and run scripts/apply_reviews.py.

Usage: python -I scripts/match_wikidata_names.py [N]   (N = how many roots, default 3000)
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_wikidata import chunks, qid, sparql, values, year  # noqa: E402

OUT = WORK / "data" / "review" / "wikidata_name_matches.csv"
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3000
STOP = {"university", "of", "the", "and", "college", "de", "la", "le", "du", "des", "school", "institute", "at", "in", "universite", "state"}


def toks(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return [t for t in re.split(r"[^a-z]+", s) if t]


def variants(name):
    clean = re.sub(r"\s+", " ", re.sub(r"\b(Jr|Sr|II|III)\.?$", "", name.strip())).strip(" ,")
    parts = clean.split(" ")
    out = {clean}
    if len(parts) > 2 and len(parts[0]) > 1 and "." not in parts[0]:
        out.add(f"{parts[0]} {parts[-1]}")
    return [v for v in out if len(v) > 4 and "." not in v.split(" ")[0]]


def lit(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    lin = json.loads((EXPL / "lineage.json").read_text())
    P = {r[0]: r for r in lin["people"]}
    has_adv = {t for _m, t, *_ in lin["edges"]}
    known_q = set()
    for r in pd.read_parquet(WORK / "data" / "external" / "merged_edges.parquet").itertuples(index=False):
        if r.source == "wikidata" and "-" in str(r.source_id):
            known_q |= set(str(r.source_id).split("-", 1))
    roots = sorted((p for p, r in P.items() if not r[3] & 1 and p not in has_adv and r[5]), key=lambda p: -P[p][5])[:N]
    by_variant = defaultdict(set)
    for p in roots:
        for v in variants(P[p][1]):
            by_variant[v].add(p)
    names = sorted(by_variant)
    print(f"{len(roots):,} roots, {len(names):,} name variants", flush=True)

    hits = defaultdict(dict)  # pid -> qid -> info
    for i, part in chunks(names, 90):
        vals = " ".join(f"{lit(n)}@{lang}" for n in part for lang in ("en", "fr", "de"))
        q = f"""SELECT ?l ?item ?birth ?adv ?advLabel ?soc WHERE {{
          VALUES ?l {{ {vals} }}
          ?item rdfs:label|skos:altLabel ?l . ?item wdt:P31 wd:Q5 .
          OPTIONAL {{ ?item wdt:P569 ?birth }}
          OPTIONAL {{ ?item wdt:P184 ?adv . OPTIONAL {{ ?adv rdfs:label ?advLabel FILTER(LANG(?advLabel) = "en") }} }}
          OPTIONAL {{ {{ ?item wdt:P106 wd:{CFG['wd_occ']} }} UNION {{ ?item wdt:P101 wd:{CFG['wd_field']} }} BIND(1 AS ?soc) }}
        }}"""
        for r in sparql(f"namematch_{i}", q):
            it = qid(r["item"])
            for p in by_variant.get(r["l"], ()):
                h = hits[p].setdefault(it, {"birth": None, "adv": {}, "soc": False, "label": r["l"]})
                h["birth"] = h["birth"] or year(r.get("birth"))
                h["soc"] = h["soc"] or r.get("soc") == "1"
                if r.get("adv"):
                    h["adv"][qid(r["adv"])] = r.get("advLabel")
        if i % 10 == 0:
            print(f"  batch {i}: {len(hits):,} roots with a name hit", flush=True)

    # unique human per root, with an advisor, not already linked
    cand = {p: next(iter(h.items())) for p, h in hits.items() if len(h) == 1}
    cand = {p: (q, h) for p, (q, h) in cand.items() if h["adv"] and q not in known_q}
    print(f"{len(cand):,} roots match exactly one human with a doctoral advisor", flush=True)
    orgs = defaultdict(set)
    for i, part in chunks(sorted({q for q, _ in cand.values()}), 150):
        q = f"""SELECT ?item ?orgLabel WHERE {{ VALUES ?item {{ {values(part)} }}
          ?item wdt:P108|wdt:P69 ?org . ?org rdfs:label ?orgLabel FILTER(LANG(?orgLabel) IN ("en", "fr", "de")) }}"""
        for r in sparql(f"namematch_org_{i}", q):
            orgs[qid(r["item"])].add(r["orgLabel"])
    adv_names = [a for _, h in cand.values() for a, lab in h["adv"].items() if not lab]
    for i, part in chunks(sorted(set(adv_names)), 150):
        q = f"""SELECT ?a (SAMPLE(?lab) AS ?l) WHERE {{ VALUES ?a {{ {values(part)} }} ?a rdfs:label ?lab }} GROUP BY ?a"""
        labs = {qid(r["a"]): r["l"] for r in sparql(f"namematch_lab_{i}", q)}
        for _, h in cand.values():
            for a in h["adv"]:
                if not h["adv"][a] and a in labs:
                    h["adv"][a] = labs[a]

    rows = []
    for p, (q, h) in cand.items():
        r = P[p]
        yr, basis = r[13], r[14]
        lo, hi = (18, 55) if basis in (1, 2, 3) else (10, 70)
        birth_ok = None if not (h["birth"] and yr) else lo <= yr - h["birth"] <= hi
        ours = {t for t in toks(r[2]) if t not in STOP and len(t) > 2}
        theirs = {t for o in orgs.get(q, ()) for t in toks(o) if t not in STOP and len(t) > 2}
        inst_ok = None if not ours or not theirs else bool(ours & theirs)
        suggest = "accept" if birth_ok and (inst_ok or (inst_ok is None and h["soc"])) else "check"
        if birth_ok is False:
            suggest = "reject"
        for a, lab in h["adv"].items():
            rows.append({"accept": "", "suggest": suggest, "student_pid": p, "student_name": r[1], "student_institution": r[2],
                         "our_phd_year": yr, "year_is_estimate": basis not in (1, 2), "wikidata_person": q, "wikidata_label": h["label"],
                         "wikidata_birth": h["birth"], "is_sociologist": h["soc"], "birth_ok": birth_ok, "inst_ok": inst_ok,
                         "wikidata_orgs": "; ".join(sorted(orgs.get(q, ())))[:200], "advisor_qid": a, "advisor_name": lab,
                         "descendants": r[5], "url": f"https://www.wikidata.org/wiki/{q}"})
    df = pd.DataFrame(rows)
    order = {"accept": 0, "check": 1, "reject": 2}
    if len(df):
        df = df.sort_values(["suggest", "descendants"], key=lambda c: c.map(order) if c.name == "suggest" else -c)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {len(df):,} candidate links for {df.student_pid.nunique() if len(df) else 0:,} people to {OUT.relative_to(ROOT)}")
    if len(df):
        print(df.groupby("suggest").student_pid.nunique().to_dict())


if __name__ == "__main__":
    main()
