"""Match external advisor->student records to AFT people and merge them into one edge list.

Inputs: data/external/*_edges.parquet with columns
    source, source_id, advisor_name, student_name, year, institution, field, url
Outputs (data/external/):
    merged_edges.parquet   advisor_pid, student_pid, source, source_id, year, institution, url,
                           advisor_match, student_match, in_aft (edge already in AFT)
    ext_people.parquet     pid (>= 900_000_000), name, institution, source  (people not in AFT)

Matching, per name:
  1. normalise (accents, punctuation, "Last, First" -> "First Last", drop suffixes like Jr.)
  2. exact key  first+last (middle names ignored)          -> candidates
  3. else key   first-initial + last                        -> candidates
  4. one candidate -> match; several -> take the one whose institution shares a word with the
     record's institution. Still ambiguous -> a new person, so two different people are never
     silently joined (duplicates are easier to fix later than false merges).
Usage: python scripts/merge_external.py [--db path]
"""

from __future__ import annotations

import re
import sys
import zlib
import unicodedata
from collections import defaultdict
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"
DB = Path(sys.argv[sys.argv.index("--db") + 1]) if "--db" in sys.argv else ROOT / "data" / "lineage.duckdb"
EXT_BASE = 900_000_000
VETTED = ["nsf_ddrig_edges.parquet", "wikidata_edges.parquet", "dissertations_edges.parquet",
          "wdanc_edges.parquet"]  # wdanc: Wikidata advisors of known people, any field (fetch_wikidata_ancestors.py)
SUFFIX = {"jr", "sr", "ii", "iii", "iv", "phd", "dr", "prof"}
STOP = {"university", "of", "the", "at", "college", "and", "state", "institute", "de", "la", "du", "des"}


def toks(s: str | None) -> list[str]:
    s = unicodedata.normalize("NFKD", s if isinstance(s, str) else "")  # NaN/None -> ""
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return [t for t in re.split(r"[^a-z]+", s) if t]


def name_parts(name: str | None) -> tuple[str, str] | None:
    if not name:
        return None
    name = name.strip()
    if "," in name:  # "Last, First Middle"
        last, _, first = name.partition(",")
        name = f"{first} {last}"
    t = [x for x in toks(name) if x not in SUFFIX]
    if len(t) < 2:
        return None
    return t[0], t[-1]


def inst_words(s: str | None) -> set[str]:
    return {t for t in toks(s) if t not in STOP and len(t) > 2}


def main() -> None:
    # only sources that have been reviewed; add a file here after checking its quality
    files = [EXT / f for f in VETTED if (EXT / f).exists()]
    if not files:
        raise SystemExit("no external edge files yet")
    cols = ["source", "source_id", "advisor_name", "student_name", "year", "institution", "field", "url", "title"]
    frames = []
    for f in files:
        d = pd.read_parquet(f)
        n0 = len(d)
        if "confidence" in d.columns:
            d = d[d.confidence != "low"]
        if f.name.startswith("wikidata"):
            # strict: one side has occupation sociologist or field sociology, not the wider subclass tree
            wp = pd.read_parquet(EXT / "wikidata_people.parquet")
            strict = set(wp[wp.sociologist_basis.apply(lambda b: any(x in ("P106:Q2306091", "P101:Q21201") for x in (b if b is not None else [])))].qid)
            d = d[d.advisor_qid.isin(strict) | d.student_qid.isin(strict)]
        if f.name.startswith("dissertations") and "degree_level" in d.columns:
            d = d[d.degree_level == "doctoral"]  # drop master's theses (MINDS@UW is mostly MS)
        if f.name.startswith("nsf_ddrig"):
            # before 2008 the NSF co-PI is often a second faculty member, not the student
            d = d[d.year.fillna(0) >= 2008]
        if len(d) < n0:
            print(f"{f.name}: kept {len(d)} of {n0} (dropped unreliable rows)")
        frames.append(d[[c for c in cols if c in d.columns]])
    df = pd.concat(frames, ignore_index=True)
    for c in cols:
        if c not in df:
            df[c] = None
    print("external records:", len(df), df.groupby("source").size().to_dict())

    con = duckdb.connect(str(DB), read_only=True)
    people = con.execute("SELECT pid, firstname, lastname, location FROM aft_people").fetchall()
    aft_edges = set(con.execute("SELECT mentor_pid, trainee_pid FROM aft_mentorship").fetchall())
    phd_loc = dict(con.execute(
        "SELECT trainee_pid, any_value(location) FROM aft_mentorship GROUP BY 1").fetchall())

    full, init = defaultdict(list), defaultdict(list)
    info, first_of = {}, {}
    for pid, first, last, loc in people:
        f, l = toks(first), toks(last)
        if not f or not l:
            continue
        info[pid] = inst_words(loc) | inst_words(phd_loc.get(pid))
        first_of[pid] = f[0]
        full[(f[0], l[-1])].append(pid)
        init[(f[0][0], l[-1])].append(pid)

    new_people: dict[tuple, int] = {}
    used_ids: set[int] = set()
    new_rows = []

    def resolve(name, institution, source, create=True):
        parts = name_parts(name)
        if not parts:
            return None, "unparseable"
        first, last = parts
        for key, label in (((first, last), "exact"), ((first[0], last), "initial")):
            cands = (full if label == "exact" else init).get(key, [])
            if label == "initial":
                # looser key, so demand more: compatible first names (a single initial, or a 3+ letter
                # prefix like Jeff/Jeffrey) AND a shared institution word. "Jo"/"Joshua" never matches.
                iw = inst_words(institution)
                def ok(p):
                    a_, b_ = sorted((first_of[p], first), key=len)
                    return b_.startswith(a_) and (len(a_) == 1 or len(a_) >= 3) and bool(iw & info.get(p, set()))
                cands = [p for p in cands if ok(p)]
                if len(cands) == 1:
                    return cands[0], "initial+institution"
                cands = []
            if len(cands) == 1:
                return cands[0], label
            if len(cands) > 1:
                iw = inst_words(institution)
                hit = [p for p in cands if iw & info.get(p, set())]
                if len(hit) == 1:
                    return hit[0], label + "+institution"
                if label == "exact":
                    break  # several people share the full name and the institution doesn't decide
        k = (first, last)
        if not create:
            return new_people.get(k), ("new" if k in new_people else "unmatched")
        if k not in new_people:
            # stable id from the name key, so merges recorded against it survive re-runs
            pid = EXT_BASE + zlib.crc32(f"{first}|{last}".encode()) % 90_000_000
            while pid in used_ids:
                pid += 1
            used_ids.add(pid)
            new_people[k] = pid
            new_rows.append({"pid": new_people[k], "name": name.strip(), "institution": institution, "source": source})
        return new_people[k], "new"

    out = []
    for r in df.itertuples(index=False):
        a, am = resolve(r.advisor_name, r.institution, r.source)
        s, sm = resolve(r.student_name, r.institution, r.source)
        if a is None or s is None or a == s:
            continue
        out.append({"advisor_pid": a, "student_pid": s, "source": r.source, "source_id": str(r.source_id),
                    "year": r.year, "institution": r.institution, "url": r.url,
                    "title": r.title if isinstance(r.title, str) else None,
                    "advisor_match": am, "student_match": sm, "in_aft": (a, s) in aft_edges})
    # ---- links entered by hand (data/manual_edges.csv, e.g. from the explorer's Data gaps tab).
    # A pid, when given, is used as is; otherwise the name is matched like any outside source.
    for man in sorted((ROOT / "data").glob("manual_edges*.csv")):
        md = pd.read_csv(man, dtype=str).fillna("")
        for i, r in enumerate(md.itertuples(index=False)):
            a = int(r.advisor_pid) if r.advisor_pid.strip() else resolve(r.advisor_name, r.institution, "manual")[0]
            s = int(r.student_pid) if r.student_pid.strip() else resolve(r.student_name, r.institution, "manual")[0]
            if a is None or s is None or a == s:
                print(f"{man.name} row {i + 2}: could not place {r.advisor_name!r} -> {r.student_name!r}")
                continue
            out.append({"advisor_pid": a, "student_pid": s, "source": "manual", "source_id": f"{man.stem}-{i + 2}",
                        "year": int(r.year) if r.year.strip().isdigit() else None, "institution": r.institution or None,
                        "url": r.url or None, "title": r.note or None, "advisor_match": "pid" if r.advisor_pid.strip() else "name",
                        "student_match": "pid" if r.student_pid.strip() else "name", "in_aft": (a, s) in aft_edges})
        print(f"{man.name}: {len(md)} rows")
    m = pd.DataFrame(out).drop_duplicates(["advisor_pid", "student_pid", "source"])
    m.to_parquet(EXT / "merged_edges.parquet", index=False)
    pd.DataFrame(new_rows).to_parquet(EXT / "ext_people.parquet", index=False)

    # ---- dissertation committees (jury / readers), a separate and weaker tie than advising.
    # Members are linked only when they match someone already known; no new people are made.
    comm = []
    dp = EXT / "dissertations_edges.parquet"
    if dp.exists():
        d = pd.read_parquet(dp)
        d = d[(d.degree_level == "doctoral") & d.committee.notna()].drop_duplicates("source_id")
        for r in d.itertuples(index=False):
            s, _ = resolve(r.student_name, r.institution, r.source, create=False)
            if s is None:
                continue
            for name in str(r.committee).split(";"):
                name = name.strip()
                if not name:
                    continue
                c, cm = resolve(name, r.institution, r.source, create=False)
                if c is None or c == s:
                    continue
                comm.append({"member_pid": c, "student_pid": s, "source": r.source, "source_id": str(r.source_id),
                             "year": r.year, "url": r.url, "match": cm})
    cm_df = pd.DataFrame(comm).drop_duplicates(["member_pid", "student_pid"]) if comm else pd.DataFrame(
        columns=["member_pid", "student_pid", "source", "source_id", "year", "url", "match"])
    cm_df.to_parquet(EXT / "merged_committees.parquet", index=False)
    print(f"committee ties: {len(cm_df)} (members matched to known people)")
    print(f"merged edges: {len(m)}  (already in AFT: {int(m.in_aft.sum())}, new: {int((~m.in_aft).sum())})")
    print("new people:", len(new_rows))
    print(m.groupby("source").agg(edges=("in_aft", "size"), already=("in_aft", "sum")).to_string())
    print("advisor match:", m.advisor_match.value_counts().to_dict())
    print("student match:", m.student_match.value_counts().to_dict())


if __name__ == "__main__":
    main()
