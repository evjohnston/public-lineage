"""Export the sociology lineage graph to compact JSON for the static explorer.

Writes explorer/data/lineage.json:
  people: [[pid, name, institution, flags, n_students, n_descendants, n_advisors,
            depth_below, component_size, hindex, openalex_id, possible_duplicate_pids, phd_year,
            year, year_basis], ...]
  year_basis: 1 recorded PhD year, 2 dissertation/grant record, 3 Wikidata birth + 28,
              4 first OpenAlex paper, 5 estimated from advisors/students, 0 unknown
  edges:  [[mentor_pid, trainee_pid, relation, source_bits, start_year, stop_year], ...]
          relation: 0 RA, 1 PhD, 2 postdoc, 3 sci
  meta:   counts and source attribution

flags is a bitmask (see FLAG_*). OpenAlex ids are included when the matcher has run.
"""

import json
import sys
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lineage.duckdb"
OUT = ROOT / "explorer" / "data" / "lineage.json"

FLAG_OUTSIDE = 1       # not tagged sociology (boundary advisor/student)
FLAG_ISOLATED = 2      # tagged sociology but no mentorship links at all
FLAG_NO_ADVISOR = 4    # in the graph, no recorded advisor
FLAG_MULTI_ADVISOR = 8
FLAG_EDUC_TAG = 16     # also listed in the education tree
FLAG_SMALL_CLUSTER = 32  # in a cluster of 3 or fewer people
FLAG_PROF_INST = 64    # doctorate from a professional / practitioner-focused institution
FLAG_EDU_AREA = 128    # research area is an education subject (leadership, curriculum, ...)
FLAG_DUPLICATE = 256   # another record looks like the same person
FLAG_EXTERNAL = 512    # person known only from an outside source (NSF, Wikidata, a repository)

EXT = ROOT / "data" / "external"
# edge source bits: 1 = Academic Family Tree, 2 = NSF dissertation grant, 4 = Wikidata, 8 = dissertation repository
SRC_AFT, SRC_NSF, SRC_WIKIDATA, SRC_DISS = 1, 2, 4, 8


def src_bit(source: str) -> int:
    return SRC_NSF if source == "nsf_ddrig" else SRC_WIKIDATA if source == "wikidata" else SRC_DISS

# Practitioner-focused doctorate granters that appear in the sociology tree (checked against the data).
PROF_INST = re.compile(
    r"capella|walden|alliant|la verne|fielding|argosy|northcentral|nova southeastern|grand canyon"
    r"|university of phoenix|california institute of integral|saybrook|chicago school of professional",
    re.I,
)
# Education subject codes (ProQuest-style). "Sociology of Education" is sociology and is not matched.
EDU_AREA = re.compile(
    r"(leadership|higher|administration|curriculum and instruction|guidance and counseling|elementary|secondary"
    r"|adult and continuing|special|vocational|teacher|early childhood) education|educational leadership",
    re.I,
)


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z ]+", " ", s).split()


def find_duplicates(people, G):
    """Pairs that look like one person: identical normalized names, or same surname and first
    initial while sharing an advisor or a student."""
    by_full, by_short = defaultdict(list), defaultdict(list)
    for pid, first, last, full in people:
        toks = norm(full)
        if not toks:
            continue
        by_full[" ".join(toks)].append(pid)
        f, l = norm(first), norm(last)
        if f and l:
            by_short[(" ".join(l), f[0][0])].append((pid, f[0]))
    dup = defaultdict(set)
    for ids in by_full.values():
        if len(ids) > 1:
            for a in ids:
                dup[a] |= set(ids) - {a}
    nbrs = lambda p: set(G.predecessors(p)) | set(G.successors(p)) if p in G else set()
    for ids in by_short.values():
        if 1 < len(ids) <= 12:
            for i, (a, fa) in enumerate(ids):
                for b, fb in ids[i + 1:]:
                    # first names must be compatible: one is a prefix of the other (W. / William)
                    if not (fa.startswith(fb) or fb.startswith(fa)):
                        continue
                    if nbrs(a) & nbrs(b):
                        dup[a].add(b)
                        dup[b].add(a)
    return dup


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    people = con.execute(
        "SELECT pid, full_name, location, in_sociology, majorarea, hindex, area, firstname, lastname FROM aft_people"
    ).fetchall()
    edges = con.execute(
        "SELECT mentor_pid, trainee_pid, min(relation) FROM aft_mentorship GROUP BY 1, 2"
    ).fetchall()
    # duplicate records resolved by scripts/resolve_duplicates.py: rewire links to the kept record
    sys.path.insert(0, str(Path(__file__).parent))
    from merges import load_merges
    MERGE = load_merges()
    R = lambda p: MERGE.get(p, p)
    people = [r for r in people if r[0] not in MERGE]
    agg = {}
    for m, t, rel in edges:
        k = (R(m), R(t))
        if k[0] != k[1]:
            agg[k] = min(rel, agg.get(k, rel))
    edges = [(m, t, r) for (m, t), r in agg.items()]
    oa = {}
    if con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'oa_author_match'"
    ).fetchone()[0]:
        oa = dict(con.execute(
            "SELECT pid, openalex_id FROM oa_author_match WHERE is_primary AND confidence IN ('high','medium')"
        ).fetchall())

    G = nx.DiGraph()
    G.add_edges_from((m, t) for m, t, _ in edges)
    edge_src = {(m, t): SRC_AFT for m, t, _ in edges}
    edge_rel = {(m, t): r for m, t, r in edges}

    # ---- outside sources (scripts/merge_external.py): confirm AFT links or add new ones
    evidence = defaultdict(list)
    ext_counts = defaultdict(lambda: {"records": 0, "confirmed": 0, "added": 0, "skipped_cycle": 0})
    merged = EXT / "merged_edges.parquet"
    if merged.exists():
        import pandas as pd
        known = {r[0] for r in people}
        ext_people = pd.read_parquet(EXT / "ext_people.parquet") if (EXT / "ext_people.parquet").exists() else pd.DataFrame()
        for r in ext_people.itertuples(index=False):
            if int(r.pid) in MERGE:
                continue
            inst = r.institution if isinstance(r.institution, str) else ""
            people.append((int(r.pid), r.name, inst, True, "", None, "", "", ""))
            known.add(int(r.pid))
        for r in pd.read_parquet(merged).itertuples(index=False):
            m, t = R(int(r.advisor_pid)), R(int(r.student_pid))
            if m == t:
                continue
            c = ext_counts[r.source]
            c["records"] += 1
            key = (m, t)
            if key not in G.edges:
                if m in G and t in G and nx.has_path(G, t, m):
                    c["skipped_cycle"] += 1  # would make someone their own academic ancestor
                    continue
                G.add_edge(m, t)
                edge_src[key] = 0
                edge_rel[key] = 1
                c["added"] += 1
            elif edge_src[key] & SRC_AFT:
                c["confirmed"] += 1
            edge_src[key] |= src_bit(r.source)
            yr = None if pd.isna(r.year) else int(r.year)
            clean_s = lambda v: v if isinstance(v, str) else None  # pandas NaN -> null
            evidence[f"{m}>{t}"].append([r.source, yr, clean_s(r.url), clean_s(r.institution), clean_s(getattr(r, "title", None))])
        edges = [(m, t, edge_rel[(m, t)]) for m, t in G.edges]
    comp_size = {}
    for comp in nx.weakly_connected_components(G):
        for n in comp:
            comp_size[n] = len(comp)

    depth_below = {}
    for n in reversed(list(nx.topological_sort(G))):
        depth_below[n] = 1 + max((depth_below[s] for s in G.successors(n)), default=-1)

    n_desc = {}
    desc_sets: dict[int, set] = {}
    for n in reversed(list(nx.topological_sort(G))):
        s = set()
        for c in G.successors(n):
            s.add(c)
            s |= desc_sets[c]
        desc_sets[n] = s
        n_desc[n] = len(s)
        # free memory for leaves' children once all parents are processed is complex; graph is small
    del desc_sets

    dup = find_duplicates([(r[0], r[7], r[8], r[1]) for r in people], G)

    # ---- training years from the AFT-MAG mentorship file (Ke et al. 2022, CC-BY-4.0): same AFT ids
    edge_years, phd_year = {}, {}
    mf = ROOT / "data" / "raw" / "aft_mag" / "mentorship.csv.gz"
    if mf.exists():
        import pandas as pd
        ms = pd.read_csv(mf, usecols=["MenteeID", "MentorID", "MentorshipType", "StartYear", "StopYear"])
        ms = ms[(ms.StopYear > 0) | (ms.StartYear > 0)]
        for r in ms.itertuples(index=False):
            k = (R(int(r.MentorID)), R(int(r.MenteeID)))
            if k in edge_src:
                edge_years[k] = [int(r.StartYear) if r.StartYear > 0 else None, int(r.StopYear) if r.StopYear > 0 else None]
                if r.MentorshipType == 1 and r.StopYear > 0:
                    phd_year[k[1]] = max(phd_year.get(k[1], 0), int(r.StopYear))
    for key, ev in evidence.items():  # outside sources carry a year (NSF award, Wikidata doctorate)
        m, t = map(int, key.split(">"))
        yrs = [e[1] for e in ev if e[1]]
        if yrs and (m, t) not in edge_years:
            edge_years[(m, t)] = [None, max(yrs)]

    # ---- best-estimate PhD year for everyone, with its basis (YEAR_BASIS codes below)
    year, basis = {}, {}
    for pid, y in phd_year.items():
        year[pid], basis[pid] = y, 1                                    # 1: recorded PhD year
    for key, ev in evidence.items():                                    # 2: year on their own dissertation record
        t = int(key.split(">")[1])
        ys = [e[1] for e in ev if e[1]]
        if ys and t not in year:
            year[t], basis[t] = max(ys), 2
    cj = ROOT / "explorer" / "data" / "careers.json"                    # 2: ORCID education entry for a PhD
    if cj.exists():
        phd_re = re.compile(r"ph\.?\s?d|doctor|doctorat|dphil|d\.phil", re.I)
        for k, (_o, _b, items) in json.loads(cj.read_text()).items():
            pid = R(int(k))
            if basis.get(pid) == 1:
                continue
            ends = [i[5] or i[4] for i in items if i[0] == "education" and phd_re.search(f"{i[3] or ''} {i[2] or ''}") and (i[5] or i[4])]
            if ends:
                year[pid], basis[pid] = max(ends), 2
    wp = EXT / "wikidata_people.parquet"
    if wp.exists() and merged.exists():                                 # 3: Wikidata birth year + 28
        import pandas as pd
        births = {r.qid: int(r.birth_year) for r in pd.read_parquet(wp).itertuples(index=False) if pd.notna(r.birth_year)}
        for r in pd.read_parquet(merged).itertuples(index=False):
            if r.source != "wikidata" or "-" not in str(r.source_id):
                continue
            aq, sq = str(r.source_id).split("-", 1)
            for pid, q in ((R(int(r.advisor_pid)), aq), (R(int(r.student_pid)), sq)):
                if pid not in year and q in births and 1700 < births[q] < 2010:
                    year[pid], basis[pid] = births[q] + 28, 3
    gaps = [year[t] - year[m] for m, t in G.edges if basis.get(m) == 1 and basis.get(t) == 1 and 0 < year[t] - year[m] < 60]
    GAP = int(np.median(gaps)) if gaps else 15

    def propagate():                                                    # 5: from dated advisors and students
        for _ in range(12):
            new = {}
            for n in G.nodes:
                if n in year:
                    continue
                est = [year[m] + GAP for m in G.predecessors(n) if m in year] + [year[c] - GAP for c in G.successors(n) if c in year]
                if est:
                    new[n] = int(round(sum(est) / len(est)))
            if not new:
                return
            for n, y in new.items():
                year[n], basis[n] = y, 5

    propagate()
    # 4: first OpenAlex paper, only for people still undated, and only from 1950 on: earlier "first
    # papers" are usually reprints of classics (Mannheim's first OpenAlex work is from the 1990s)
    try:
        first = con.execute("""
            SELECT m.pid, min(a.year) FROM oa_author_match m JOIN oa_authorships a ON a.author_id = m.openalex_id
            WHERE m.confidence IN ('high', 'medium') AND a.year BETWEEN 1950 AND 2030 GROUP BY 1""").fetchall()
        for pid, y in first:
            pid = R(pid)
            if pid not in year:
                year[pid], basis[pid] = int(y), 4
    except duckdb.Error:
        pass
    propagate()

    rows = []
    for pid, name, loc, in_soc, major, hindex, area, _first, _last in people:
        tags = set((major or "").split(","))
        in_g = pid in G
        f = 0
        if not in_soc:
            f |= FLAG_OUTSIDE
        if in_soc and not in_g:
            f |= FLAG_ISOLATED
        if in_g and G.in_degree(pid) == 0:
            f |= FLAG_NO_ADVISOR
        if in_g and G.in_degree(pid) > 1:
            f |= FLAG_MULTI_ADVISOR
        if "educ" in tags:
            f |= FLAG_EDUC_TAG
        if in_g and comp_size[pid] <= 3:
            f |= FLAG_SMALL_CLUSTER
        if PROF_INST.search(loc or ""):
            f |= FLAG_PROF_INST
        if EDU_AREA.search(area or ""):
            f |= FLAG_EDU_AREA
        if pid in dup:
            f |= FLAG_DUPLICATE
        if pid >= 900_000_000:
            f |= FLAG_EXTERNAL
        rows.append([
            pid, clean(name), clean(loc), f,
            G.out_degree(pid) if in_g else 0, n_desc.get(pid, 0),
            G.in_degree(pid) if in_g else 0, depth_below.get(pid, 0),
            comp_size.get(pid, 1), hindex, oa.get(pid),
            sorted(dup[pid]) if pid in dup else None,
            phd_year.get(pid), year.get(pid), basis.get(pid, 0),
        ])

    sizes = sorted({len(c) for c in nx.weakly_connected_components(G)}, reverse=True)
    meta = {
        "outside_sources": {k: dict(v) for k, v in ext_counts.items()},
        "people": len(rows),
        "edges": len(edges),
        "clusters": nx.number_weakly_connected_components(G),
        "largest_cluster": sizes[0] if sizes else 0,
        "openalex_matched": len(oa),
        "merged_duplicates": len(MERGE),
        "edges_with_years": len(edge_years),
        "people_with_phd_year": len(phd_year),
        "year_basis_counts": {str(k): sum(1 for v in basis.values() if v == k) for k in range(1, 6)},
        "advisor_student_gap_years": GAP,
        "source": "Academic Family Tree export, snapshot 2022-03-12 (CC-BY-4.0)",
        "citation": "Liénard, J.F., Achakulvisut, T., Acuna, D.E. et al. Intellectual synthesis in mentorship determines success in academic careers. Nat Commun 9, 4840 (2018).",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out_edges = [[m, t, r, edge_src.get((m, t), SRC_AFT), *(edge_years.get((m, t)) or [None, None])] for m, t, r in edges]
    # dissertation committee ties (separate from advising): [member, student, year, url]
    committees = []
    cf = EXT / "merged_committees.parquet"
    if cf.exists():
        import pandas as pd
        known = {r[0] for r in rows}
        for r in pd.read_parquet(cf).itertuples(index=False):
            a, b = R(int(r.member_pid)), R(int(r.student_pid))
            if a != b and a in known and b in known:
                committees.append([a, b, None if pd.isna(r.year) else int(r.year), r.url if isinstance(r.url, str) else None])
    meta["committee_ties"] = len(committees)
    # ties read from dissertation text (scripts/read_dissertations.py), unverified:
    # [named_pid, student_pid, section (0 advisor, 1 jury, 2 acknowledgments), year, pdf_url, snippet]
    text_ties = []
    tf = EXT / "dissertation_text_mentions.parquet"
    if tf.exists():
        import pandas as pd
        known = {r[0] for r in rows}
        sec = {"advisor": 0, "jury": 1, "ack": 2}
        seen = set()
        for r in pd.read_parquet(tf).itertuples(index=False):
            if pd.isna(r.student_pid):
                continue
            a, b = R(int(r.named_pid)), R(int(r.student_pid))
            if a == b or a not in known or b not in known or (a, b) in seen:
                continue
            seen.add((a, b))
            text_ties.append([a, b, sec.get(r.section, 2), None if pd.isna(r.year) else int(r.year),
                              r.url if isinstance(r.url, str) else None, (r.snippet or "")[:160]])
    meta["text_ties"] = len(text_ties)
    OUT.write_text(json.dumps({"meta": meta, "people": rows, "edges": out_edges, "evidence": evidence, "committees": committees, "text_ties": text_ties}, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)", meta)


if __name__ == "__main__":
    main()
