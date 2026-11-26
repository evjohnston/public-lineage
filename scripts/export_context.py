"""Export schools of thought, detected communities, subfields and institutions for the explorer.

Writes explorer/data/context.json, joined to lineage.json by pid:
  person:      {pid: [phd_locid, faculty_locid, closest_school_idx, community_idx, [subfield_idx...],
                     [topic_idx...], [works, citations, h_index] | null]}
  schools:     curated (data/schools.json); members = founders + all descendants
  communities: Louvain communities on the undirected advisor graph (components >= 50 people)
  subfields:   research-area tags (people.area, comma-separated), with inheritance rates
  institutions:{locid: name, geo, PhDs, advisors, placement in/out}
  placements:  [[phd_locid, faculty_locid, n], ...]   where a person trained -> where they later advised
               (or held a recorded affiliation)

Usage: python scripts/export_context.py [--db path]
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
DB = Path(sys.argv[sys.argv.index("--db") + 1]) if "--db" in sys.argv else WORK / "data" / "lineage.duckdb"
SCHOOLS = WORK / "data" / "schools.json"
OUT = EXPL / "context.json"
MIN_SUBFIELD = 40
MIN_COMMUNITY = 30


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    people = con.execute(
        "SELECT pid, full_name, locid, location, area, in_sociology FROM aft_people"
    ).fetchall()
    sys.path.insert(0, str(Path(__file__).parent))
    from merges import load_merges
    MERGE = load_merges()
    R = lambda p: MERGE.get(p, p)
    people = [p for p in people if p[0] not in MERGE]
    in_soc = {p[0]: p[5] for p in people}
    name = {p[0]: " ".join((p[1] or "").split()) for p in people}
    edges = [(R(m), R(t), rel, loc) for m, t, rel, loc in con.execute(
        "SELECT mentor_pid, trainee_pid, relation, locid FROM aft_mentorship"
    ).fetchall() if R(m) != R(t)]
    locs = {r[0]: r[1:] for r in con.execute(
        "SELECT locid, location, country, city, state, lat, lon FROM aft_locations"
    ).fetchall()}

    G = nx.DiGraph()
    G.add_edges_from((m, t) for m, t, _, _ in edges if m in in_soc and t in in_soc)
    # links from outside sources (scripts/merge_external.py), skipping any that would form a cycle
    ext = WORK / "data" / "external"
    if (ext / "merged_edges.parquet").exists():
        import pandas as pd
        if (ext / "ext_people.parquet").exists():
            for r in pd.read_parquet(ext / "ext_people.parquet").itertuples(index=False):
                if int(r.pid) in MERGE:
                    continue
                in_soc[int(r.pid)] = True
                name[int(r.pid)] = r.name
        for r in pd.read_parquet(ext / "merged_edges.parquet").itertuples(index=False):
            m, t = R(int(r.advisor_pid)), R(int(r.student_pid))
            if m != t and m in in_soc and t in in_soc and not G.has_edge(m, t) and not (m in G and t in G and nx.has_path(G, t, m)):
                G.add_edge(m, t)

    # ---------------------------------------------------------------- PhD vs current institution
    phd = {}
    for m, t, rel, loc in sorted(edges, key=lambda e: (e[2] != 1, e[2])):  # PhD links first
        if loc and t not in phd:
            phd[t] = loc
    # Faculty institution: where the person advised students (most common), else a recorded
    # non-mentored affiliation. The listed "current" institution is mostly the PhD school itself.
    adv_at = defaultdict(Counter)
    for m, t, rel, loc in edges:
        if loc:
            adv_at[m][loc] += 1
    affil = defaultdict(Counter)
    for pid, loc in con.execute("SELECT pid, locid FROM aft_affiliation WHERE locid IS NOT NULL").fetchall():
        affil[pid][loc] += 1
    current = {}
    for pid in in_soc:
        if adv_at[pid]:
            current[pid] = adv_at[pid].most_common(1)[0][0]
        elif affil[pid] and affil[pid].most_common(1)[0][0] != phd.get(pid):
            current[pid] = affil[pid].most_common(1)[0][0]

    # ---------------------------------------------------------------- curated schools
    spec = json.loads(SCHOOLS.read_text())["schools"]
    schools, dist_to = [], []
    for s in spec:
        founders = [f for f in s["founders"] if f in G or f in in_soc]
        d = {}
        for f in founders:
            if f not in G:
                d[f] = 0
                continue
            for n, k in nx.single_source_shortest_path_length(G, f).items():
                d[n] = min(d.get(n, 99), k)
        dist_to.append(d)
        schools.append({"id": s["id"], "name": s["name"], "note": s.get("note", ""),
                        "founders": founders, "size": len(d)})
    closest = {}
    for i, d in enumerate(dist_to):
        for n, k in d.items():
            if n not in closest or k < closest[n][1]:
                closest[n] = (i, k)
    for i, s in enumerate(schools):
        members = dist_to[i]
        s["depth"] = max(members.values()) if members else 0
        s["exclusive"] = sum(1 for n in members if closest[n][0] == i)
        inst = Counter(phd.get(n) for n in members if phd.get(n))
        s["top_institutions"] = [[l, c] for l, c in inst.most_common(8)]
        s["overlap"] = sorted(
            ([schools[j]["id"], len(set(members) & set(dist_to[j]))] for j in range(len(schools)) if j != i
             and set(members) & set(dist_to[j])), key=lambda x: -x[1])[:5]

    # ---------------------------------------------------------------- detected communities
    U = G.to_undirected()
    community = {}
    comms = []
    for comp in nx.connected_components(U):
        if len(comp) < 50:
            continue
        for c in nx.community.louvain_communities(U.subgraph(comp), seed=7, resolution=1.0):
            if len(c) < MIN_COMMUNITY:
                continue
            idx = len(comms)
            # name after the member with the most descendants inside the community, and its main institution
            soc_members = [n for n in c if in_soc.get(n)] or list(c)
            top = max(soc_members, key=lambda n: len(nx.descendants(G, n) & c))
            inst = Counter(phd.get(n) for n in c if phd.get(n))
            main_loc = inst.most_common(1)[0][0] if inst else None
            comms.append({"top": top, "size": len(c), "main_institution": main_loc,
                          "institution_share": round(inst.most_common(1)[0][1] / len(c), 2) if inst else 0,
                          "label": f"{name[top]} line" + (f" · {locs.get(main_loc, ['?'])[0]}" if main_loc in locs else "")})
            for n in c:
                community[n] = idx
    comms_order = sorted(range(len(comms)), key=lambda i: -comms[i]["size"])
    remap = {old: new for new, old in enumerate(comms_order)}
    comms = [comms[i] for i in comms_order]
    community = {n: remap[c] for n, c in community.items()}

    # ---------------------------------------------------------------- subfields
    tags_of = {}
    for pid, _, _, _, area, soc in people:
        if soc and area:
            tags_of[pid] = {t.strip() for t in area.split(",") if t.strip() and t.strip() != "General"}
    counts = Counter(t for ts in tags_of.values() for t in ts)
    subfields = [t for t, c in counts.most_common() if c >= MIN_SUBFIELD]
    sf_idx = {t: i for i, t in enumerate(subfields)}
    pairs = [(m, t) for m, t in G.edges() if m in tags_of and t in tags_of]
    n_tagged = len(tags_of)
    sf_out = []
    for t in subfields:
        adv = [(m, s) for m, s in pairs if t in tags_of[m]]
        inherited = sum(1 for m, s in adv if t in tags_of[s])
        base = counts[t] / n_tagged
        sf_out.append({"name": t, "size": counts[t],
                       "advised_pairs": len(adv),
                       "inheritance": round(inherited / len(adv), 3) if adv else None,
                       "baseline": round(base, 3)})

    # ---------------------------------------------------------------- institutions + placements
    place = Counter()
    for pid, loc in phd.items():
        cur = current.get(pid)
        if cur and in_soc.get(pid):
            place[(loc, cur)] += 1
    used = set(phd.values()) | set(current.values())
    inst = {}
    phds = Counter(loc for pid, loc in phd.items() if in_soc.get(pid))
    advisors = defaultdict(set)
    for m, t, rel, loc in edges:
        if loc:
            advisors[loc].add(m)
    faculty = Counter(loc for pid, loc in current.items() if in_soc.get(pid))
    out_tot, in_tot, self_hire = Counter(), Counter(), Counter()
    for (a, b), n in place.items():
        if a == b:
            self_hire[a] += n
        else:
            out_tot[a] += n
            in_tot[b] += n
    for loc in used:
        if loc not in locs or not (phds[loc] or faculty[loc]):
            continue
        nm, country, city, state, lat, lon = locs[loc]
        inst[loc] = {"name": nm, "country": country, "city": city, "lat": lat, "lon": lon,
                     "phds": phds[loc], "advisors": len(advisors[loc]), "people": faculty[loc],
                     "placed_out": out_tot[loc], "hired_in": in_tot[loc], "self_hired": self_hire[loc]}
    placements = [[a, b, n] for (a, b), n in place.items() if a != b and a in inst and b in inst]

    # ---------------------------------------------------------------- faculty hiring census
    # Wapman et al. 2022 (CC-BY-3.0-US): US sociology faculty 2011-2020, PhD institution -> employer.
    hiring_flows, hiring_meta = [], None
    hf, hm = WORK / "data" / "external" / f"faculty_hiring_{FIELD}_flows.parquet", WORK / "data" / "external" / "faculty_hiring_inst_map.parquet"
    if hf.exists() and hm.exists():
        import pandas as pd
        fl, mp = pd.read_parquet(hf), pd.read_parquet(hm)
        to_loc = {int(r.hiring_id): int(r.locid) for r in mp.itertuples() if pd.notna(r.locid)}
        agg = Counter()
        for r in fl.itertuples():
            a, b = to_loc.get(int(r.phd_institution_id)), to_loc.get(int(r.hiring_institution_id))
            if a is not None and b is not None:
                agg[(a, b)] += int(r.n)
        hiring_flows = [[a, b, n] for (a, b), n in agg.items()]
        ranks = pd.read_parquet(WORK / "data" / "external" / f"faculty_hiring_{FIELD}_institutions.parquet")
        for r in ranks.itertuples():
            loc = to_loc.get(int(r.institution_id))
            if loc is None:
                continue
            if loc not in inst and loc in locs:
                nm, country, city, state, lat, lon = locs[loc]
                inst[loc] = {"name": nm, "country": country, "city": city, "lat": lat, "lon": lon, "phds": 0,
                             "advisors": 0, "people": 0, "placed_out": 0, "hired_in": 0, "self_hired": 0}
            if loc in inst:
                inst[loc]["prestige_rank"] = int(r.ordinal_prestige_rank) + 1  # 1 = top; r.prestige_rank is a 0-1 score
                inst[loc]["faculty_census"] = int(r.non_attrited_faculty + r.attrited_faculty) if pd.notna(r.attrited_faculty) else None
        for (a, b), n in agg.items():
            for loc in (a, b):
                if loc not in inst and loc in locs:
                    nm, country, city, state, lat, lon = locs[loc]
                    inst[loc] = {"name": nm, "country": country, "city": city, "lat": lat, "lon": lon, "phds": 0,
                                 "advisors": 0, "people": 0, "placed_out": 0, "hired_in": 0, "self_hired": 0}
        hiring_meta = {"faculty": int(fl.n.sum()), "faculty_matched": int(sum(agg.values())), "years": "2011-2020",
                       "citation": "Wapman, Zhang, Clauset & Larremore, Nature 610, 120-127 (2022)", "license": "CC-BY-3.0-US"}

    # ---------------------------------------------------------------- OpenAlex publication topics
    # each person's top 3 topics (summed over their matched OpenAlex profiles), plus works/citations
    top_topics, oa_stats, topic_info = {}, {}, {}
    oa_path = WORK / "data" / "external" / "openalex_authors.parquet"
    if oa_path.exists():
        import pandas as pd
        oa = pd.read_parquet(oa_path)
        amap = defaultdict(list)
        for aid, pid in con.execute("SELECT openalex_id, pid FROM oa_author_match WHERE confidence IN ('high','medium')").fetchall():
            amap[aid].append(R(pid))
        weights = defaultdict(Counter)
        for r in oa.itertuples():
            if not isinstance(r.topics, str):
                continue
            for pid in amap.get(r.openalex_id, []):
                for tid, name, field, sub, n in json.loads(r.topics):
                    weights[pid][tid] += n or 0
                    topic_info[tid] = (name, field, sub)
                st = oa_stats.setdefault(pid, [0, 0, 0])
                st[0] += int(r.works_count or 0); st[1] += int(r.cited_by_count or 0); st[2] = max(st[2], int(r.h_index or 0))
        top_topics = {pid: [t for t, _ in w.most_common(3)] for pid, w in weights.items()}
    tcount = Counter(t for ts in top_topics.values() for t in ts)
    topic_list = [t for t, c in tcount.most_common() if c >= 25]
    t_idx = {t: i for i, t in enumerate(topic_list)}
    t_pairs = [(m, t) for m, t in G.edges() if m in top_topics and t in top_topics]
    n_top = len(top_topics)
    topics_out = []
    for t in topic_list:
        adv = [(m, s) for m, s in t_pairs if t in top_topics[m]]
        inh = sum(1 for m, s in adv if t in top_topics[s])
        name, field, sub = topic_info[t]
        topics_out.append({"id": t, "name": name, "field": field, "subfield": sub, "size": tcount[t],
                           "advised_pairs": len(adv), "inheritance": round(inh / len(adv), 3) if adv else None,
                           "baseline": round(tcount[t] / n_top, 4) if n_top else None})

    person = {}
    for pid in in_soc:
        rec = [phd.get(pid), current.get(pid), closest[pid][0] if pid in closest else None,
               community.get(pid), sorted(sf_idx[t] for t in tags_of.get(pid, ()) if t in sf_idx),
               [t_idx[t] for t in top_topics.get(pid, []) if t in t_idx], oa_stats.get(pid)]
        if any(v not in (None, []) for v in rec):
            person[pid] = rec

    out = {"schools": schools, "communities": comms, "subfields": sf_out, "topics": topics_out,
           "institutions": inst, "placements": placements, "hiring_flows": hiring_flows, "hiring": hiring_meta, "person": person,
           "meta": {"note": "PhD institution = location on the person's own advisor link. Faculty institution = where they advised students, else a recorded affiliation. No PhD years are available in this export."}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB): {len(schools)} schools, {len(comms)} communities, "
          f"{len(subfields)} subfields, {len(inst)} institutions, {len(placements)} placement links")
    for s in schools:
        print(f"  {s['name']:28s} {s['size']:>5} members, {s['exclusive']:>5} closest, depth {s['depth']}")


if __name__ == "__main__":
    main()
