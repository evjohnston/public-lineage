"""Stream AFT authorPub files from Zenodo and keep only our sociology people's DOI links.

Keeps rows where the link is plausibly valid (score_total > 0.3 per AFT docs, or a human
confirmed it) and the person has not been human-rejected. Output: data/raw/aft/authorpub_soc.parquet
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
DB = WORK / "data" / "lineage.duckdb"
OUT = AUTHORPUB
BASE = "https://zenodo.org/records/6349537/files/authorPub{:02d}.csv.gz?download=1"
PARTS = [0, 5, 10, 15, 20, 25, 30]


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    if not all((ROOT / "data" / "raw" / "aft" / f"authorPub{p:02d}.csv.gz").exists() for p in PARTS):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("CREATE TEMP TABLE ids AS SELECT pid FROM aft_people")
    chunks = []
    for i, part in enumerate(PARTS):
        local = ROOT / "data" / "raw" / "aft" / f"authorPub{part:02d}.csv.gz"
        url = str(local) if local.exists() else BASE.format(part)  # local copy when downloaded
        con.execute(
            f"""
            CREATE TEMP TABLE part{i} AS
            SELECT CAST(pid AS BIGINT) pid, CAST(pubid AS BIGINT) pubid,
                   TRY_CAST(score_total AS DOUBLE) score_total,
                   TRY_CAST(score_human AS INT) score_human,
                   lower(trim(doi)) doi, pmid, s2id, TRY_CAST(citations AS INT) citations
            FROM read_csv('{url}', all_varchar=true, nullstr=['NULL',''], header=true,
                          compression='gzip')
            WHERE CAST(pid AS BIGINT) IN (SELECT pid FROM ids)
              AND doi IS NOT NULL
              AND (TRY_CAST(score_total AS DOUBLE) > 0.3 OR TRY_CAST(score_human AS INT) = 1)
              AND coalesce(TRY_CAST(score_human AS INT), 0) <> -1
            """
        )
        n = con.execute(f"SELECT count(*) FROM part{i}").fetchone()[0]
        print(f"authorPub{part:02d}: kept {n:,}", flush=True)
        chunks.append(f"SELECT * FROM part{i}")
    con.execute(f"COPY ({' UNION ALL '.join(chunks)}) TO '{OUT}' (FORMAT parquet)")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
