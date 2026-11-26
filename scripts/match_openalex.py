"""Match AFT sociology people to OpenAlex author IDs.

Steps (each cached in data/lineage.duckdb, so the script is resumable):
  1. s2     - for people with a Semantic Scholar author id, fetch their papers' DOIs (S2 batch API)
  2. works  - look up every candidate DOI in OpenAlex (50 per request) and cache the authorships
  3. orcid  - exact ORCID -> OpenAlex author lookup
  4. vote   - for each person, the OpenAlex author with a compatible name who appears on the most
              of their DOIs wins. Extra IDs that also clear the bar are kept as split profiles.

Outputs table oa_author_match(pid, openalex_id, method, votes, n_dois, is_primary, confidence).

Usage: python scripts/match_openalex.py [s2|works|orcid|vote|all]
"""

from __future__ import annotations

import re
import sys
import time
import unicodedata
from pathlib import Path

import duckdb
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
DB = WORK / "data" / "lineage.duckdb"
AUTHORPUB = AUTHORPUB
ENV = dotenv_values(ROOT / ".env")
UA = {"User-Agent": "academic-lineage-research/0.1"}
OA = "https://api.openalex.org"
# keeps the OpenAlex budget bounded for very prolific people. Larger fields get fewer per person: a few
# shared DOIs already identify the author (3 votes = high confidence), and the daily budget is ~10k requests.
MAX_DOIS_PER_PERSON = 60 if FIELD == "sociology" else 6
WORKERS = 1 if FIELD == "sociology" else 4  # parallel /works requests
MIN_USD_LEFT = 0.05


# --------------------------------------------------------------------------- helpers
def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z ]+", " ", s).strip()


def name_compatible(first: str | None, last: str | None, cand: str | None) -> bool:
    """AFT surname tokens all appear in the candidate name, and first initials agree."""
    last_t, cand_t = norm(last).split(), norm(cand).split()
    if not last_t or not cand_t or not all(t in cand_t for t in last_t):
        return False
    f = norm(first)
    return not f or cand_t[0][0] == f[0]


def oa_get(client: httpx.Client, path: str, **params) -> dict | None:
    for attempt in range(5):
        r = client.get(OA + path, params={**params, "api_key": ENV["OPENALEX_API_KEY"]})
        if r.status_code == 200:
            left = float(r.headers.get("x-ratelimit-remaining-usd", "1"))
            if left < MIN_USD_LEFT:
                raise SystemExit(f"OpenAlex daily budget nearly used (${left:.3f} left); rerun tomorrow.")
            return r.json()
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        print("OpenAlex", r.status_code, r.text[:200])
        return None
    return None


def init(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS s2_author_dois (pid BIGINT, s2id VARCHAR, doi VARCHAR, year INT)")
    con.execute("CREATE TABLE IF NOT EXISTS s2_fetched (s2id VARCHAR PRIMARY KEY)")
    con.execute("CREATE TABLE IF NOT EXISTS oa_dois_fetched (doi VARCHAR PRIMARY KEY)")
    con.execute(
        """CREATE TABLE IF NOT EXISTS oa_authorships (
             doi VARCHAR, work_id VARCHAR, year INT, author_id VARCHAR, author_name VARCHAR,
             raw_name VARCHAR, position VARCHAR, institution_ids VARCHAR[])"""
    )


# --------------------------------------------------------------------------- step 1: S2
def step_s2(con: duckdb.DuckDBPyConnection) -> None:
    todo = con.execute(
        """SELECT s2id, min(pid) FROM aft_people
           WHERE s2id ~ '^\\d+$' AND s2id <> '0' AND s2id NOT IN (SELECT s2id FROM s2_fetched)
           GROUP BY s2id"""
    ).fetchall()
    print(f"S2: {len(todo):,} authors to fetch")
    pid_of = dict(todo)
    ids = list(pid_of)
    with httpx.Client(timeout=120, headers={**UA, "x-api-key": ENV["SEMANTIC_SCHOLAR_API_KEY"]}) as c:
        for i in range(0, len(ids), 100):
            batch = ids[i : i + 100]
            for attempt in range(6):
                time.sleep(1.1)
                r = c.post(
                    "https://api.semanticscholar.org/graph/v1/author/batch",
                    params={"fields": "papers.externalIds,papers.year"},
                    json={"ids": batch},
                )
                if r.status_code == 200:
                    break
                time.sleep(2 ** attempt)
            else:
                print("S2 batch failed", r.status_code, r.text[:200])
                continue
            rows = []
            for sid, a in zip(batch, r.json()):
                for p in (a or {}).get("papers") or []:
                    doi = ((p.get("externalIds") or {}).get("DOI") or "").lower().strip()
                    if doi:
                        rows.append((pid_of[sid], sid, doi, p.get("year")))
            if rows:
                con.executemany("INSERT INTO s2_author_dois VALUES (?,?,?,?)", rows)
            con.executemany("INSERT OR IGNORE INTO s2_fetched VALUES (?)", [(s,) for s in batch])
            print(f"  S2 {i + len(batch):,}/{len(ids):,}", flush=True)


# --------------------------------------------------------------------------- step 2: works
def candidate_dois(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""CREATE OR REPLACE TEMP VIEW person_dois AS
            WITH ev AS (
              SELECT pid, doi FROM read_parquet('{AUTHORPUB}')
              UNION SELECT p.pid, s.doi FROM s2_author_dois s
                    JOIN aft_people p ON p.s2id = s.s2id
            ), ranked AS (
              SELECT pid, doi, row_number() OVER (PARTITION BY pid ORDER BY hash(doi)) rn FROM ev
            )
            SELECT pid, doi FROM ranked WHERE rn <= {MAX_DOIS_PER_PERSON}"""
    )


def step_works(con: duckdb.DuckDBPyConnection) -> None:
    candidate_dois(con)
    todo = [
        r[0]
        for r in con.execute(
            """SELECT DISTINCT doi FROM person_dois
               WHERE doi NOT IN (SELECT doi FROM oa_dois_fetched) AND doi NOT LIKE '%|%'"""
        ).fetchall()
    ]
    # commas split OpenAlex filters, so those DOIs go one at a time (singleton lookups are free)
    singles = [x for x in todo if "," in x]
    todo = [x for x in todo if "," not in x]
    if singles:
        print(f"  {len(singles):,} DOIs with commas -> single lookups")
        with httpx.Client(timeout=60, headers=UA) as c:
            for doi in singles:
                w = oa_get(c, "/works/https://doi.org/" + doi, select="id,doi,publication_year,authorships")
                if w:
                    rows = [(doi, w["id"].rsplit("/", 1)[-1], w.get("publication_year"), a["author"]["id"].rsplit("/", 1)[-1],
                             a["author"].get("display_name"), a.get("raw_author_name"), a.get("author_position"),
                             [i["id"].rsplit("/", 1)[-1] for i in a.get("institutions") or [] if i.get("id")])
                            for a in w.get("authorships") or [] if (a.get("author") or {}).get("id")]
                    if rows:
                        con.executemany("INSERT INTO oa_authorships VALUES (?,?,?,?,?,?,?,?)", rows)
                con.execute("INSERT OR IGNORE INTO oa_dois_fetched VALUES (?)", [doi])
    print(f"OpenAlex works: {len(todo):,} DOIs to look up (~{len(todo) // 50 + 1:,} requests)")
    from concurrent.futures import ThreadPoolExecutor
    batches = [todo[i : i + 50] for i in range(0, len(todo), 50)]
    with httpx.Client(timeout=120, headers=UA) as c, ThreadPoolExecutor(WORKERS) as pool:
        def fetch(batch):
            try:
                return batch, oa_get(c, "/works", filter="doi:" + "|".join(batch),
                                     select="id,doi,publication_year,authorships", **{"per-page": 50})
            except httpx.HTTPError:  # timeout or dropped connection: left unfetched for the next run
                return batch, None
        for n_done, (batch, d) in enumerate(pool.map(fetch, batches)):
            i = n_done * 50
            if d is None:
                continue
            rows = []
            for w in d["results"]:
                doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
                for a in w.get("authorships") or []:
                    au = a.get("author") or {}
                    if not au.get("id"):
                        continue
                    rows.append((
                        doi, w["id"].rsplit("/", 1)[-1], w.get("publication_year"),
                        au["id"].rsplit("/", 1)[-1], au.get("display_name"), a.get("raw_author_name"),
                        a.get("author_position"),
                        [inst["id"].rsplit("/", 1)[-1] for inst in a.get("institutions") or [] if inst.get("id")],
                    ))
            if rows:
                con.executemany("INSERT INTO oa_authorships VALUES (?,?,?,?,?,?,?,?)", rows)
            con.executemany("INSERT OR IGNORE INTO oa_dois_fetched VALUES (?)", [(x,) for x in batch])
            if (i // 50) % 50 == 0:
                print(f"  works {i + len(batch):,}/{len(todo):,}", flush=True)


# --------------------------------------------------------------------------- step 3: orcid
def step_orcid(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    rows = con.execute(
        r"""SELECT pid, orcid_id FROM aft_people
            WHERE orcid_id ~ '\d{4}-\d{4}-\d{4}-\d{3}[\dX]'"""
    ).fetchall()
    out = []
    with httpx.Client(timeout=60, headers=UA) as c:
        for i in range(0, len(rows), 50):
            batch = rows[i : i + 50]
            d = oa_get(c, "/authors", filter="orcid:" + "|".join(o for _, o in batch),
                       select="id,orcid", **{"per-page": 50})
            by_orcid = {(a.get("orcid") or "").rsplit("/", 1)[-1]: a["id"].rsplit("/", 1)[-1]
                        for a in (d or {}).get("results", [])}
            out += [(pid, by_orcid[o]) for pid, o in batch if o in by_orcid]
    print(f"ORCID: {len(out)}/{len(rows)} matched")
    return out


# --------------------------------------------------------------------------- step 4: vote
def step_vote(con: duckdb.DuckDBPyConnection, orcid_hits: list[tuple]) -> None:
    candidate_dois(con)
    people = {r[0]: r[1:] for r in con.execute("SELECT pid, firstname, lastname FROM aft_people").fetchall()}
    ev = con.execute(
        """SELECT pd.pid, pd.doi, a.author_id, a.author_name, a.raw_name
           FROM person_dois pd JOIN oa_authorships a USING (doi)"""
    ).fetchall()
    n_dois = dict(con.execute(
        "SELECT pid, count(DISTINCT doi) FROM person_dois WHERE doi IN (SELECT doi FROM oa_dois_fetched) GROUP BY pid"
    ).fetchall())

    votes: dict[int, dict[str, set]] = {}
    for pid, doi, aid, name, raw in ev:
        first, last = people[pid]
        if name_compatible(first, last, name) or name_compatible(first, last, raw):
            votes.setdefault(pid, {}).setdefault(aid, set()).add(doi)

    out = []
    for pid, aid in orcid_hits:
        out.append((pid, aid, "orcid", None, n_dois.get(pid, 0), True, "high"))
    orcid_pids = {p for p, _ in orcid_hits}
    for pid, cands in votes.items():
        ranked = sorted(((len(d), a) for a, d in cands.items()), reverse=True)
        top_v = ranked[0][0]
        n = n_dois.get(pid, 0)
        for rank, (v, aid) in enumerate(ranked):
            primary = rank == 0 and pid not in orcid_pids
            # keep secondaries only if they look like a split profile of the same person
            if rank > 0 and not (v >= 2 and v >= 0.2 * top_v):
                break
            conf = "high" if v >= 3 or (v >= 2 and v / max(n, 1) >= 0.5) else ("medium" if v == 2 else "low")
            out.append((pid, aid, "doi_vote", v, n, primary, conf))

    con.execute(
        """CREATE OR REPLACE TABLE oa_author_match (
             pid BIGINT, openalex_id VARCHAR, method VARCHAR, votes INT, n_dois INT,
             is_primary BOOLEAN, confidence VARCHAR)"""
    )
    con.executemany("INSERT INTO oa_author_match VALUES (?,?,?,?,?,?,?)", out)
    print(con.execute(
        """SELECT confidence, count(DISTINCT pid) FROM oa_author_match WHERE is_primary
           GROUP BY 1 ORDER BY 1"""
    ).fetchall())


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    con = duckdb.connect(str(DB))
    init(con)
    if step in ("s2", "all"):
        step_s2(con)
    if step in ("works", "all"):
        step_works(con)
    if step in ("vote", "orcid", "all"):
        hits = step_orcid(con)
        if step != "orcid":
            step_vote(con, hits)
    con.close()


if __name__ == "__main__":
    main()
