"""Co-author network among people in the lineage data, from OpenAlex authorships.

Two people co-authored when both appear on the same OpenAlex work. People enter through their
OpenAlex author ids (high/medium matches in oa_author_match, split profiles included). Coverage is
bounded by the works we looked up: up to 60 DOIs per person from AFT and Semantic Scholar.

Writes explorer/data/coauthors.json:
  edges:  [[pid_a, pid_b, n_works, first_year, last_year, mentor_flag], ...]   pid_a < pid_b
          mentor_flag: 1 = a advised b, 2 = b advised a, 0 = no advising link
  degree: {pid: total distinct OpenAlex co-authors, inside or outside the dataset}
  meta:   counts and caveats
Usage: python scripts/export_coauthors.py
"""

import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
DB = Path(sys.argv[sys.argv.index("--db") + 1]) if "--db" in sys.argv else WORK / "data" / "lineage.duckdb"
OUT = EXPL / "coauthors.json"
LIN = EXPL / "lineage.json"

sys.path.insert(0, str(Path(__file__).parent))
from merges import load_merges  # noqa: E402


def main() -> None:
    MERGE = load_merges()
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute("""
        WITH m AS (SELECT DISTINCT pid, openalex_id FROM oa_author_match WHERE confidence IN ('high', 'medium')),
        w AS (SELECT DISTINCT a.work_id, m.pid, a.year FROM oa_authorships a JOIN m ON m.openalex_id = a.author_id)
        SELECT w1.pid, w2.pid, w1.work_id, w1.year FROM w w1 JOIN w w2 ON w1.work_id = w2.work_id AND w1.pid <> w2.pid
    """).fetchall()
    deg_rows = con.execute("""
        WITH m AS (SELECT DISTINCT pid, openalex_id FROM oa_author_match WHERE confidence IN ('high', 'medium')),
        mine AS (SELECT DISTINCT m.pid, a.work_id, m.openalex_id FROM oa_authorships a JOIN m ON m.openalex_id = a.author_id)
        SELECT mine.pid, count(DISTINCT a.author_id) FROM mine JOIN oa_authorships a ON a.work_id = mine.work_id
        WHERE a.author_id <> mine.openalex_id GROUP BY 1
    """).fetchall()

    R = lambda p: MERGE.get(p, p)
    pairs = {}
    for a, b, work, year in rows:
        a, b = R(a), R(b)
        if a >= b:
            continue
        e = pairs.setdefault((a, b), [set(), None, None])
        e[0].add(work)
        if year:
            e[1] = year if e[1] is None else min(e[1], year)
            e[2] = year if e[2] is None else max(e[2], year)

    advises = set()
    if LIN.exists():
        for m, t, *_ in json.loads(LIN.read_text())["edges"]:
            advises.add((m, t))
    edges = []
    for (a, b), (works, y0, y1) in pairs.items():
        flag = 1 if (a, b) in advises else 2 if (b, a) in advises else 0
        edges.append([a, b, len(works), y0, y1, flag])
    edges.sort(key=lambda e: -e[2])
    degree = {}
    for pid, n in deg_rows:
        degree[R(pid)] = max(degree.get(R(pid), 0), n)

    adv_pairs = sum(1 for e in edges if e[5])
    meta = {
        "pairs": len(edges), "pairs_2plus": sum(1 for e in edges if e[2] >= 2), "people": len({p for e in edges for p in e[:2]}),
        "advisor_student_coauthors": adv_pairs,
        "note": "Co-authorship from OpenAlex works found via each person's DOIs (up to 60 per person); only people matched to OpenAlex appear.",
    }
    OUT.write_text(json.dumps({"meta": meta, "edges": edges, "degree": degree}, separators=(",", ":"), allow_nan=False))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)", meta)


if __name__ == "__main__":
    main()
