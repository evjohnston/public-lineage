"""Build the sociology subgraph from the Academic Family Tree (AFT) Zenodo export.

Source: https://zenodo.org/records/6349537 (snapshot 2022-03-12, CC-BY-4.0)
Cite: Liénard et al. (2018) Nature Communications 9:4840.

Schema notes (https://academictree.org/export.php):
  connect.pid1 = trainee, connect.pid2 = mentor (0 => institutional affiliation, no mentor)
  connect.relation: 0=undergrad RA, 1=grad student, 2=postdoc, 3=research scientist,
                    4=collaboration (not mentorship)

Scope rule: a node is "in sociology" if 'sociology' is in its majorarea tags. We keep every
edge that touches at least one sociology person, so out-of-field mentors/trainees (e.g. an
economist advising a sociologist) are kept as boundary nodes with in_sociology = false.

Output: data/lineage.duckdb with tables aft_people, aft_mentorship, aft_collab,
aft_affiliation, aft_locations.
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
RAW = ROOT / "data" / "raw" / "aft"
DB = WORK / "data" / "lineage.duckdb"

RELATION_LABELS = """
    CASE relation
        WHEN 0 THEN 'undergrad_ra'
        WHEN 1 THEN 'grad_student'
        WHEN 2 THEN 'postdoc'
        WHEN 3 THEN 'research_scientist'
        WHEN 4 THEN 'collaboration'
    END
"""


def main() -> None:
    con = duckdb.connect(str(DB))
    read = lambda name: (
        f"read_csv('{RAW / name}', all_varchar=true, nullstr=['NULL',''], header=true)"
    )

    con.execute(f"CREATE OR REPLACE TEMP TABLE people_all AS SELECT * FROM {read('people.csv.gz')}")
    con.execute(f"CREATE OR REPLACE TEMP TABLE connect_all AS SELECT * FROM {read('connect.csv.gz')}")

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE soc_ids AS
        SELECT CAST(pid AS BIGINT) AS pid FROM people_all
        WHERE list_contains(string_split(coalesce(majorarea, ''), ','), '{CFG["aft_tag"]}')
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE edges_touching AS
        SELECT CAST(cid AS BIGINT) cid, CAST(pid1 AS BIGINT) pid1, CAST(pid2 AS BIGINT) pid2,
               CAST(relation AS INT) relation, location, CAST(locid AS BIGINT) locid,
               CAST(dateadded AS TIMESTAMP) dateadded
        FROM connect_all
        WHERE CAST(pid1 AS BIGINT) IN (SELECT pid FROM soc_ids)
           OR CAST(pid2 AS BIGINT) IN (SELECT pid FROM soc_ids)
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE TABLE aft_mentorship AS
        SELECT cid, pid2 AS mentor_pid, pid1 AS trainee_pid, relation,
               {RELATION_LABELS} AS relation_label, location, locid, dateadded
        FROM edges_touching
        WHERE pid2 <> 0 AND relation IN (0, 1, 2, 3) AND pid1 <> pid2
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE aft_collab AS
        SELECT cid, pid1, pid2, location, locid, dateadded
        FROM edges_touching WHERE pid2 <> 0 AND relation = 4
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE aft_affiliation AS
        SELECT cid, pid1 AS pid, location, locid, dateadded
        FROM edges_touching WHERE pid2 = 0
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE aft_people AS
        WITH ids AS (
            SELECT pid FROM soc_ids
            UNION SELECT mentor_pid FROM aft_mentorship
            UNION SELECT trainee_pid FROM aft_mentorship
            UNION SELECT pid1 FROM aft_collab
            UNION SELECT pid2 FROM aft_collab
        )
        SELECT CAST(p.pid AS BIGINT) pid, p.firstname, p.middlename, p.lastname,
               concat_ws(' ', p.firstname, p.middlename, p.lastname) AS full_name,
               p.degrees, p.location, CAST(p.locid AS BIGINT) locid, p.area, p.majorarea,
               p.award, TRY_CAST(p.hindex AS INT) hindex, p.orcid_id, p.s2id, p.homepage,
               CAST(p.dateadded AS TIMESTAMP) dateadded,
               CAST(p.pid AS BIGINT) IN (SELECT pid FROM soc_ids) AS in_sociology
        FROM people_all p JOIN ids ON CAST(p.pid AS BIGINT) = ids.pid
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE TABLE aft_locations AS
        SELECT CAST(locid AS BIGINT) locid, location, country, city, state,
               TRY_CAST(lon AS DOUBLE) lon, TRY_CAST(lat AS DOUBLE) lat
        FROM {read('locations.csv.gz')}
        WHERE CAST(locid AS BIGINT) IN (
            SELECT locid FROM aft_people UNION SELECT locid FROM aft_mentorship
            UNION SELECT locid FROM aft_affiliation)
        """
    )

    for t in ["aft_people", "aft_mentorship", "aft_collab", "aft_affiliation", "aft_locations"]:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"{t:18s} {n:>8,}")
    print(
        con.execute(
            "SELECT relation_label, count(*) FROM aft_mentorship GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    con.close()


if __name__ == "__main__":
    main()
