"""Fetch the OpenAlex author record for every matched person (singleton lookups are free).

Gives each person's ORCID (to join ORCID careers), research topics (for the Publication topics
view), citation and works counts, and last known institutions.

Output: data/external/openalex_authors.parquet
  openalex_id, orcid, display_name, works_count, cited_by_count, h_index, topics (JSON text:
  list of [topic_id, name, field, subfield, count]), last_inst (list of names), first_year, last_year
Resumable: already-fetched ids are skipped.
Usage: python -I scripts/fetch_openalex_authors.py
"""

import json
import time
from pathlib import Path

import duckdb
import httpx
import pandas as pd
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external" / "openalex_authors.parquet"
KEY = dotenv_values(ROOT / ".env")["OPENALEX_API_KEY"]
UA = {"User-Agent": "academic-lineage-research/0.1"}
SELECT = "id,orcid,display_name,works_count,cited_by_count,summary_stats,last_known_institutions,topics,counts_by_year"


def main():
    con = duckdb.connect(str(ROOT / "data" / "lineage.duckdb"), read_only=True)
    ids = [r[0] for r in con.execute(
        "SELECT DISTINCT openalex_id FROM oa_author_match WHERE confidence IN ('high', 'medium')").fetchall()]
    con.close()
    old = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=["openalex_id"])
    done = set(old.openalex_id)
    todo = [i for i in ids if i not in done]
    print(f"{len(ids):,} authors, {len(todo):,} to fetch", flush=True)
    rows = []
    with httpx.Client(headers=UA, timeout=60) as c:
        for n, aid in enumerate(todo, 1):
            r = None
            for attempt in range(6):
                try:
                    r = c.get(f"https://api.openalex.org/authors/{aid}", params={"api_key": KEY, "select": SELECT})
                except httpx.HTTPError:  # dropped connection, timeout: wait and retry
                    time.sleep(2 ** attempt); continue
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt); continue
                break
            if r is None:
                continue  # still failing; left for the next run
            if r.status_code == 200:
                a = r.json()
                years = [y["year"] for y in a.get("counts_by_year") or [] if y.get("works_count")]
                rows.append({
                    "openalex_id": aid, "orcid": (a.get("orcid") or "").rsplit("/", 1)[-1] or None,
                    "display_name": a.get("display_name"), "works_count": a.get("works_count"),
                    "cited_by_count": a.get("cited_by_count"), "h_index": (a.get("summary_stats") or {}).get("h_index"),
                    # JSON text: parquet can't hold a list mixing strings and counts
                    "topics": json.dumps([[t["id"].rsplit("/", 1)[-1], t.get("display_name"), (t.get("field") or {}).get("display_name"),
                                (t.get("subfield") or {}).get("display_name"), t.get("count")] for t in (a.get("topics") or [])[:10]]),
                    "last_inst": [i.get("display_name") for i in a.get("last_known_institutions") or []],
                    "first_year": min(years) if years else None, "last_year": max(years) if years else None,
                })
            else:
                rows.append({"openalex_id": aid})  # mark as tried (e.g. merged/deleted author)
            if n % 500 == 0 or n == len(todo):
                pd.concat([old, pd.DataFrame(rows)], ignore_index=True).to_parquet(OUT, index=False)
                print(f"  {n:,}/{len(todo):,}", flush=True)
            time.sleep(0.08)
    print("done")


if __name__ == "__main__":
    main()
