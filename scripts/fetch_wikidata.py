"""Pull doctoral advisor -> student links for sociologists from Wikidata.

Scope: any pair where the advisor or the student is a sociologist, i.e. has
  occupation (P106) sociologist (Q2306091) or one of its subclasses, or
  field of work (P101) sociology (Q21201).
Pairs come from both doctoral advisor (P184, on the student) and doctoral student
(P185, on the advisor), unioned.

Steps (every raw SPARQL response is cached in data/raw/wikidata/, so reruns are free):
  1. subclasses of sociologist, and subclasses of doctorate (for degree qualifiers)
  2. sociologist QIDs (occupation, field of work)
  3. pairs: 2 properties x 2 sides x 2 sociologist definitions = 8 modest queries
  4. person attributes in VALUES batches: core (label/dates/ORCID/OpenAlex),
     employers, educated at (with degree + end-date qualifiers), doctoral thesis
     (P1026 or thesis items authored via P50) with its institution/date.

Outputs:
  data/external/wikidata_edges.parquet
  data/external/wikidata_people.parquet

Usage: python scripts/fetch_wikidata.py [--refresh]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "wikidata"
OUT = ROOT / "data" / "external"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = {
    "User-Agent": "academic-lineage-research/0.1 (personal research project)",
    "Accept": "application/sparql-results+json",
}
PAUSE = 2.0  # seconds between live queries
BATCH = 250  # QIDs per attribute query
REFRESH = "--refresh" in sys.argv

SOCIOLOGIST = "Q2306091"
SOCIOLOGY = "Q21201"
DOCTORATE = "Q849697"
DOCTORAL_THESIS = "Q187685"

_client = httpx.Client(headers=UA, timeout=httpx.Timeout(90.0, connect=20.0))
_last_call = 0.0


# --------------------------------------------------------------------------- SPARQL helpers
def sparql(name: str, query: str, tries: int = 5) -> list[dict]:
    """Run a query (or load it from cache). Returns bindings as {var: value} dicts."""
    global _last_call
    RAW.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(query.encode()).hexdigest()[:12]
    path = RAW / f"{name}_{h}.json"
    if path.exists() and not REFRESH:
        data = json.loads(path.read_text())
    else:
        for attempt in range(tries):
            wait = PAUSE - (time.time() - _last_call)
            if wait > 0:
                time.sleep(wait)
            _last_call = time.time()
            try:
                r = _client.post(ENDPOINT, data={"query": query, "format": "json"})
            except httpx.HTTPError as e:
                print(f"  {name}: {type(e).__name__}, retrying", flush=True)
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 200:
                data = r.json()
                path.write_text(json.dumps(data))
                break
            if r.status_code == 429:
                delay = int(r.headers.get("Retry-After", "60"))
                print(f"  {name}: 429, sleeping {delay}s", flush=True)
                time.sleep(delay + 1)
                continue
            print(f"  {name}: HTTP {r.status_code}, retrying", flush=True)
            time.sleep(15 * (attempt + 1))
        else:
            raise RuntimeError(f"query {name} failed after {tries} tries")
    return [{k: v["value"] for k, v in b.items()} for b in data["results"]["bindings"]]


def qid(uri: str | None) -> str | None:
    return uri.rsplit("/", 1)[-1] if uri else None


def year(ts: str | None) -> int | None:
    """Wikidata xsd:dateTime -> year (handles BCE '-' prefix)."""
    if not ts:
        return None
    try:
        neg = ts.startswith("-")
        y = int(ts.lstrip("+-").split("-", 1)[0])
        return -y if neg else y
    except ValueError:
        return None


def values(qids) -> str:
    return " ".join(f"wd:{q}" for q in qids)


def chunks(xs, n):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield i // n, xs[i : i + n]


# --------------------------------------------------------------------------- queries
Q_SUBCLASSES = "SELECT DISTINCT ?c WHERE {{ ?c wdt:P279* wd:{root} . }}"

Q_SOC_OCC = """SELECT DISTINCT ?p ?c WHERE {{
  VALUES ?c {{ {classes} }}
  ?p wdt:P106 ?c .
}}"""

Q_SOC_FIELD = f"SELECT DISTINCT ?p WHERE {{ ?p wdt:P101 wd:{SOCIOLOGY} . }}"

# Pair queries. {soc} is the sociologist pattern on variable ?s.
SOC_OCC_PATTERN = "VALUES ?c {{ {classes} }} ?s wdt:P106 ?c ."
SOC_FIELD_PATTERN = f"?s wdt:P101 wd:{SOCIOLOGY} ."
Q_PAIRS = {
    # P185 on the advisor
    "p185_adv_soc": "SELECT DISTINCT ?adv ?stu WHERE {{ {soc} BIND(?s AS ?adv) ?adv wdt:P185 ?stu . }}",
    "p185_stu_soc": "SELECT DISTINCT ?adv ?stu WHERE {{ {soc} BIND(?s AS ?stu) ?adv wdt:P185 ?stu . }}",
    # P184 on the student
    "p184_stu_soc": "SELECT DISTINCT ?adv ?stu WHERE {{ {soc} BIND(?s AS ?stu) ?stu wdt:P184 ?adv . }}",
    "p184_adv_soc": "SELECT DISTINCT ?adv ?stu WHERE {{ {soc} BIND(?s AS ?adv) ?stu wdt:P184 ?adv . }}",
}

Q_CORE = """SELECT ?p ?label ?birth ?death ?orcid ?openalex WHERE {{
  VALUES ?p {{ {vals} }}
  OPTIONAL {{ ?p rdfs:label ?label . FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?p wdt:P569 ?birth . }}
  OPTIONAL {{ ?p wdt:P570 ?death . }}
  OPTIONAL {{ ?p wdt:P496 ?orcid . }}
  OPTIONAL {{ ?p wdt:P10283 ?openalex . }}
}}"""

# Fallback label (multilingual 'mul' or any language) for people with no English label.
Q_ANYLABEL = """SELECT ?p (SAMPLE(?l) AS ?label) WHERE {{
  VALUES ?p {{ {vals} }}
  ?p rdfs:label ?l .
}} GROUP BY ?p"""

# All labels, for people whose English (or fallback) label has no Latin letters at all,
# which in practice is usually a mislabelled en label (e.g. Arabic/Chinese text in the en slot).
Q_ALLLABELS = """SELECT ?p ?l (LANG(?l) AS ?lang) WHERE {{
  VALUES ?p {{ {vals} }}
  ?p rdfs:label ?l .
}}"""
LATIN_PREF = ["en", "mul", "de", "fr", "es", "it", "nl", "pt", "sv", "da", "nb", "pl", "cs"]

Q_EMPLOYER = """SELECT ?p ?e ?eLabel WHERE {{
  VALUES ?p {{ {vals} }}
  ?p wdt:P108 ?e .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
}}"""

Q_EDUCATED = """SELECT ?p ?e ?eLabel ?deg ?end ?pit WHERE {{
  VALUES ?p {{ {vals} }}
  ?p p:P69 ?st . ?st ps:P69 ?e .
  OPTIONAL {{ ?st pq:P512 ?deg . }}
  OPTIONAL {{ ?st pq:P582 ?end . }}
  OPTIONAL {{ ?st pq:P585 ?pit . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
}}"""

# Thesis: either linked from the person (P1026) or a doctoral-thesis item authored by them (P50).
# Institution from 'dissertation submitted to' (P4101) or 'conferred by' (P1027).
Q_THESIS = """SELECT ?p ?t ?inst ?instLabel ?date WHERE {{
  VALUES ?p {{ {vals} }}
  {{ ?p wdt:P1026 ?t . }} UNION {{ ?t wdt:P50 ?p ; wdt:P31 wd:{thesis} . }}
  OPTIONAL {{ ?t wdt:P4101|wdt:P1027 ?inst . }}
  OPTIONAL {{ ?t wdt:P577|wdt:P585 ?date . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
}}"""


def batched(name: str, template: str, qids: list[str], **fmt) -> list[dict]:
    rows = []
    for i, chunk in chunks(sorted(qids), BATCH):
        rows += sparql(f"{name}_{i:04d}", template.format(vals=values(chunk), **fmt))
    print(f"  {name}: {len(rows)} rows", flush=True)
    return rows


# --------------------------------------------------------------------------- main
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    print("1. class hierarchies", flush=True)
    soc_classes = sorted({qid(r["c"]) for r in sparql("subclasses_sociologist", Q_SUBCLASSES.format(root=SOCIOLOGIST))})
    doc_degrees = {qid(r["c"]) for r in sparql("subclasses_doctorate", Q_SUBCLASSES.format(root=DOCTORATE))}
    print(f"  {len(soc_classes)} sociologist classes, {len(doc_degrees)} doctorate classes")

    print("2. sociologists", flush=True)
    occ_rows = sparql("sociologists_occupation", Q_SOC_OCC.format(classes=values(soc_classes)))
    field_rows = sparql("sociologists_field", Q_SOC_FIELD)
    soc_basis: dict[str, set[str]] = {}
    for r in occ_rows:
        soc_basis.setdefault(qid(r["p"]), set()).add(f"P106:{qid(r['c'])}")
    for r in field_rows:
        soc_basis.setdefault(qid(r["p"]), set()).add(f"P101:{SOCIOLOGY}")
    print(f"  {len(soc_basis)} sociologists ({len(occ_rows)} occupation rows, {len(field_rows)} field rows)")

    print("3. pairs", flush=True)
    patterns = {
        "occ": SOC_OCC_PATTERN.format(classes=values(soc_classes)),
        "field": SOC_FIELD_PATTERN,
    }
    pair_via: dict[tuple[str, str], set[str]] = {}
    for pname, tmpl in Q_PAIRS.items():
        for sname, soc in patterns.items():
            rows = sparql(f"pairs_{pname}_{sname}", tmpl.format(soc=soc))
            print(f"  {pname}/{sname}: {len(rows)}", flush=True)
            for r in rows:
                a, s = qid(r["adv"]), qid(r["stu"])
                if a and s and a.startswith("Q") and s.startswith("Q") and a != s:
                    pair_via.setdefault((a, s), set()).add(pname.split("_")[0].upper())
    print(f"  {len(pair_via)} unique pairs")

    people = sorted({q for pair in pair_via for q in pair})
    students = sorted({s for _, s in pair_via})
    print(f"4. attributes for {len(people)} people", flush=True)

    core = batched("core", Q_CORE, people)
    names, birth, death = {}, {}, {}
    orcid: dict[str, set] = {}
    openalex: dict[str, set] = {}
    for r in core:
        p = qid(r["p"])
        if r.get("label"):
            names[p] = r["label"]
        b, d = year(r.get("birth")), year(r.get("death"))
        # multiple dates: keep the earliest birth / latest death year
        if b is not None:
            birth[p] = min(b, birth.get(p, b))
        if d is not None:
            death[p] = max(d, death.get(p, d))
        if r.get("orcid"):
            orcid.setdefault(p, set()).add(r["orcid"])
        if r.get("openalex"):
            openalex.setdefault(p, set()).add(r["openalex"])
    missing = [p for p in people if p not in names]
    if missing:
        for r in batched("anylabel", Q_ANYLABEL, missing):
            names[qid(r["p"])] = r["label"]
    nonlatin = [p for p in people if p in names and not re.search(r"[A-Za-z]", names[p])]
    if nonlatin:
        cands: dict[str, dict[str, str]] = {}
        for r in batched("alllabels", Q_ALLLABELS, nonlatin):
            if re.search(r"[A-Za-z]", r["l"]):
                cands.setdefault(qid(r["p"]), {})[r["lang"]] = r["l"]
        for p, by_lang in cands.items():
            lang = next((l for l in LATIN_PREF if l in by_lang), sorted(by_lang)[0])
            names[p] = by_lang[lang]
        print(f"  replaced {len(cands)} of {len(nonlatin)} non-Latin labels", flush=True)

    employers: dict[str, list] = {}
    for r in batched("employer", Q_EMPLOYER, people):
        lst = employers.setdefault(qid(r["p"]), [])
        if r["eLabel"] not in lst:
            lst.append(r["eLabel"])

    educated: dict[str, list] = {}
    doctorate: dict[str, list[tuple]] = {}  # p -> [(year, institution)]
    for r in batched("educated", Q_EDUCATED, people):
        p = qid(r["p"])
        lst = educated.setdefault(p, [])
        if r["eLabel"] not in lst:
            lst.append(r["eLabel"])
        if qid(r.get("deg")) in doc_degrees:
            doctorate.setdefault(p, []).append((year(r.get("end")) or year(r.get("pit")), r["eLabel"]))

    thesis: dict[str, list[tuple]] = {}
    for r in batched("thesis", Q_THESIS, students, thesis=DOCTORAL_THESIS):
        thesis.setdefault(qid(r["p"]), []).append((year(r.get("date")), r.get("instLabel")))

    def best(entries: list[tuple]) -> tuple[int | None, str | None]:
        """Earliest dated doctorate, institution from that entry (or any with an institution)."""
        if not entries:
            return None, None
        dated = sorted([e for e in entries if e[0] is not None], key=lambda e: e[0])
        y = dated[0][0] if dated else None
        inst = next((e[1] for e in dated if e[1]), None) or next((e[1] for e in entries if e[1]), None)
        return y, inst

    # ------------------------------------------------------------------ edges
    edges = []
    for (a, s), via in sorted(pair_via.items()):
        y, inst = best(doctorate.get(s, []))
        ty, tinst = best(thesis.get(s, []))
        edges.append(
            {
                "source": "wikidata",
                "source_id": f"{a}-{s}",
                "advisor_name": names.get(a, a),
                "student_name": names.get(s, s),
                "advisor_qid": a,
                "student_qid": s,
                "year": y if y is not None else ty,
                "institution": inst or tinst,
                "field": "sociology",
                "url": f"https://www.wikidata.org/wiki/{s}",
                "via": ",".join(sorted(via)),  # which property asserted the link: P184, P185 or both
            }
        )
    edges_df = pd.DataFrame(edges)
    edges_df["year"] = edges_df["year"].astype("Int64")
    edges_df.to_parquet(OUT / "wikidata_edges.parquet", index=False)

    # ------------------------------------------------------------------ people
    people_df = pd.DataFrame(
        {
            "qid": people,
            "name": [names.get(p, p) for p in people],
            "birth_year": pd.array([birth.get(p) for p in people], dtype="Int64"),
            "death_year": pd.array([death.get(p) for p in people], dtype="Int64"),
            "orcid": ["|".join(sorted(orcid[p])) if p in orcid else None for p in people],
            "openalex_id": ["|".join(sorted(openalex[p])) if p in openalex else None for p in people],
            "employers": [employers.get(p, []) for p in people],
            "educated_at": [educated.get(p, []) for p in people],
            "is_sociologist": [p in soc_basis for p in people],
            "sociologist_basis": [sorted(soc_basis.get(p, [])) for p in people],
        }
    )
    people_df.to_parquet(OUT / "wikidata_people.parquet", index=False)

    print(f"\nwrote {len(edges_df)} edges, {len(people_df)} people to {OUT}")
    print(f"  ORCID: {people_df.orcid.notna().sum()}, OpenAlex: {people_df.openalex_id.notna().sum()}, "
          f"either: {(people_df.orcid.notna() | people_df.openalex_id.notna()).sum()}")
    print(f"  edges with year: {edges_df.year.notna().sum()}, with institution: {edges_df.institution.notna().sum()}")


if __name__ == "__main__":
    main()
