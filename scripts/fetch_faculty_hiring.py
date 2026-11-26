"""Fetch the US faculty hiring network data (Wapman, Zhang, Clauset & Larremore, Nature 2022)
and write the Sociology slice.

Sources
- Zenodo record 6941651 (v1, July 2022): us-faculty-hiring-networks.zip, archived for reference.
- GitHub LarremoreLab/us-faculty-hiring-networks, pinned commit (Aug 2026 export fix). This is
  the primary source: the Zenodo zip predates two upstream bug fixes and is missing most
  edges (Sociology: 447 edges / 1,377 faculty in Zenodo vs 3,259 edges / 4,676 faculty here).

The dataset is aggregated: one row per (employing institution, doctoral institution) pair per
network, with counts (Total/Men/Women). There are no person-level records, person ids, names,
PhD years or academic ranks, so no per-person table can be built from it. Outputs:

- data/external/faculty_hiring_{FIELD}_flows.parquet         one row per PhD -> hiring pair
- data/external/faculty_hiring_{FIELD}_institutions.parquet  prestige/production ranks

Raw files are untrusted; run with `python -I scripts/fetch_faculty_hiring.py [--refresh]`.
"""

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

import duckdb
import httpx

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
RAW = ROOT / "data" / "raw" / "faculty_hiring"
OUT = WORK / "data" / "external"

ZENODO_API = "https://zenodo.org/api/records/6941651"
GH_COMMIT = "841e9c96f949677aadbffded10a002586ff65cc4"
GH_RAW = f"https://raw.githubusercontent.com/LarremoreLab/us-faculty-hiring-networks/{GH_COMMIT}"
GH_FILES = ["README.md", "data/edge-lists.csv", "data/institution-stats.csv",
            "data/stats.csv", "data/yearly-stats.csv"]

HFIELD = CFG["hiring"]  # field name in the census
RELATED = [] if FIELD != "sociology" else ["Criminal Justice and Criminology", "Social Work", "Gender Studies",
           "Human Development and Family Sciences", "Anthropology"]


def download(client: httpx.Client, url: str, dest: Path, refresh: bool) -> None:
    if dest.exists() and not refresh:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(dest)
    print(f"downloaded {dest.relative_to(ROOT)} ({dest.stat().st_size:,} bytes)")


def fetch(refresh: bool) -> None:
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        rec = client.get(ZENODO_API).raise_for_status().json()
        for f in rec["files"]:
            dest = RAW / f["key"]
            download(client, f["links"]["self"], dest, refresh)
            algo, want = f["checksum"].split(":", 1)
            got = hashlib.new(algo, dest.read_bytes()).hexdigest()
            if got != want:
                sys.exit(f"checksum mismatch for {dest}: {got} != {want}")
        for name in GH_FILES:
            download(client, f"{GH_RAW}/{name}", RAW / "github_main" / Path(name).name, refresh)

    # Extract only the README and data CSVs from the Zenodo zip (it also bundles a .git dir).
    zpath = RAW / "us-faculty-hiring-networks.zip"
    dest = (RAW / "extracted").resolve()
    with zipfile.ZipFile(zpath) as z:
        for m in z.namelist():
            if m.endswith("/") or "/.git/" in m:
                continue
            target = (dest / m).resolve()
            if not target.is_relative_to(dest):
                sys.exit(f"unsafe path in zip: {m}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(m))


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    edges = RAW / "github_main" / "edge-lists.csv"
    inst = RAW / "github_main" / "institution-stats.csv"
    con = duckdb.connect()
    con.execute(f"""
        CREATE VIEW edges AS SELECT * FROM read_csv('{edges}', header=true, all_varchar=true);
        CREATE VIEW inst AS SELECT * FROM read_csv('{inst}', header=true, all_varchar=true);
        CREATE TABLE soc_inst AS
        SELECT CAST(InstitutionId AS INT) institution_id, InstitutionName institution_name,
               CAST(PrestigeRank AS DOUBLE) prestige_rank,
               CAST(OrdinalPrestigeRank AS INT) ordinal_prestige_rank,
               TRY_CAST(ProductionRank AS INT) production_rank,
               CAST(NonAttritedFaculty AS INT) non_attrited_faculty,
               CAST(AttritedFaculty AS INT) attrited_faculty,
               CAST(NonAttritionEvents AS INT) non_attrition_events,
               CAST(AttritionEvents AS INT) attrition_events
        FROM inst WHERE TaxonomyLevel = 'Field' AND TaxonomyValue = '{HFIELD}'
        ORDER BY ordinal_prestige_rank;
        CREATE TABLE flows AS
        SELECT CAST(e.DegreeInstitutionId AS INT) phd_institution_id,
               e.DegreeInstitutionName phd_institution,
               CAST(e.InstitutionId AS INT) hiring_institution_id,
               e.InstitutionName hiring_institution,
               CAST(e.Total AS INT) n,
               CAST(e.Men AS INT) n_men,
               CAST(e.Women AS INT) n_women,
               CAST(e.Total AS INT) - CAST(e.Men AS INT) - CAST(e.Women AS INT) n_gender_unknown,
               e.DegreeInstitutionId = e.InstitutionId self_hire,
               p.ordinal_prestige_rank phd_ordinal_prestige_rank,
               h.ordinal_prestige_rank hiring_ordinal_prestige_rank
        FROM edges e
        LEFT JOIN soc_inst p ON p.institution_id = CAST(e.DegreeInstitutionId AS INT)
        LEFT JOIN soc_inst h ON h.institution_id = CAST(e.InstitutionId AS INT)
        WHERE e.TaxonomyLevel = 'Field' AND e.TaxonomyValue = '{HFIELD}'
        ORDER BY n DESC, phd_institution, hiring_institution;
    """)
    bad = con.execute("SELECT count(*) FROM flows WHERE n IS NULL OR phd_institution_id IS NULL "
                      "OR n_gender_unknown < 0").fetchone()[0]
    if bad:
        sys.exit(f"{bad} malformed sociology edges")
    con.execute(f"COPY flows TO '{OUT / f'faculty_hiring_{FIELD}_flows.parquet'}' (FORMAT parquet)")
    con.execute(f"COPY soc_inst TO '{OUT / f'faculty_hiring_{FIELD}_institutions.parquet'}' "
                "(FORMAT parquet)")

    print(con.execute("SELECT count(*) edges, sum(n) faculty, sum(n_men) men, sum(n_women) women, "
                      "sum(n_gender_unknown) unknown, sum(n) FILTER (WHERE self_hire) self_hires, "
                      "count(DISTINCT hiring_institution_id) hiring_insts, "
                      "count(DISTINCT phd_institution_id) phd_insts FROM flows").df().T)
    print(f"ranked sociology institutions: {con.execute('SELECT count(*) FROM soc_inst').fetchone()[0]}")
    print(con.execute("SELECT phd_institution, hiring_institution, n FROM flows LIMIT 10").df())
    names = ", ".join(f"'{r}'" for r in [HFIELD, *RELATED])
    print(con.execute(f"SELECT TaxonomyValue field, count(*) edges, sum(CAST(Total AS INT)) faculty "
                      f"FROM edges WHERE TaxonomyLevel = 'Field' AND TaxonomyValue IN ({names}) "
                      "GROUP BY 1 ORDER BY 3 DESC").df())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download raw files")
    args = ap.parse_args()
    fetch(args.refresh)
    build()


if __name__ == "__main__":
    main()
