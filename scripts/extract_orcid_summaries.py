"""Stream the ORCID Public Data File summaries archive and keep only what this project needs.

ORCID_<year>_<month>_summaries.tar.gz (~57 GB, CC0) holds one XML record per ORCID iD. We read it
as a stream (nothing is extracted to disk) and keep a record when either:
  * its ORCID iD is one we already know (AFT, Wikidata, OpenAlex matches), or
  * an education or employment entry mentions sociology (department, role or organisation).

Output: data/external/orcid_affiliations.parquet, one row per education/employment entry:
  orcid, given_names, family_name, kind (education|employment), organization, city, country,
  department, role, start_year, end_year, known (bool: iD was already in our data)

Usage: python -I scripts/extract_orcid_summaries.py <path/to/summaries.tar.gz> [--limit N]
The archive is untrusted input: parsed with defusedxml, never extracted.
"""

from __future__ import annotations

import json
import re
import sys
import tarfile
import time
from pathlib import Path

import pandas as pd
from defusedxml import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"
OUT = EXT / "orcid_affiliations.parquet"
SOC = re.compile(rb"sociolog|soziolog|socjolog", re.I)
ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")
NS = {
    "record": "http://www.orcid.org/ns/record", "person": "http://www.orcid.org/ns/person",
    "personal-details": "http://www.orcid.org/ns/personal-details", "common": "http://www.orcid.org/ns/common",
    "activities": "http://www.orcid.org/ns/activities", "education": "http://www.orcid.org/ns/education",
    "employment": "http://www.orcid.org/ns/employment",
}


def known_orcids() -> set[str]:
    ids: set[str] = set()
    for path, col in [(EXT / "wikidata_people.parquet", "orcid"), (ROOT / "data" / "raw" / "aft_mag" / "researcher.csv.gz", "ORCID")]:
        if path.exists():
            df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, dtype=str, usecols=[col])
            for v in df[col].dropna():
                ids.update(ORCID_RE.findall(str(v)))
    try:
        import duckdb
        con = duckdb.connect(str(ROOT / "data" / "lineage.duckdb"), read_only=True)
        for (v,) in con.execute("SELECT orcid_id FROM aft_people WHERE orcid_id IS NOT NULL").fetchall():
            ids.update(ORCID_RE.findall(v))
    except Exception:
        pass  # DB may be locked by the matcher; the other sources still apply
    return ids


def text(el, path):
    x = el.find(path, NS)
    return x.text.strip() if x is not None and x.text else None


def year(el, which):
    y = text(el, f"common:{which}/common:year")
    return int(y) if y and y.isdigit() else None


def parse(raw: bytes, known: bool) -> list[dict]:
    root = ET.fromstring(raw)
    orcid = text(root, "common:orcid-identifier/common:path")
    given = text(root, "person:person/person:name/personal-details:given-names")
    family = text(root, "person:person/person:name/personal-details:family-name")
    rows = []
    for kind in ("education", "employment"):
        for s in root.iterfind(f".//{kind}:{kind}-summary", NS):
            org = s.find("common:organization", NS)
            rows.append({
                "orcid": orcid, "given_names": given, "family_name": family, "kind": kind,
                "organization": text(org, "common:name") if org is not None else None,
                "city": text(org, "common:address/common:city") if org is not None else None,
                "country": text(org, "common:address/common:country") if org is not None else None,
                "department": text(s, "common:department-name"), "role": text(s, "common:role-title"),
                "start_year": year(s, "start-date"), "end_year": year(s, "end-date"), "known": known,
            })
    return rows


def main() -> None:
    src = Path(sys.argv[1])
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    known = known_orcids()
    print(f"known ORCID iDs: {len(known):,}", flush=True)
    rows, seen, kept, t0 = [], 0, 0, time.time()
    with tarfile.open(src, mode="r|gz") as tar:
        for m in tar:
            if not m.isfile() or not m.name.endswith(".xml"):
                continue
            seen += 1
            f = tar.extractfile(m)
            if f is None:
                continue
            raw = f.read()
            oid = m.name.rsplit("/", 1)[-1][:-4]
            is_known = oid in known
            if is_known or SOC.search(raw):
                try:
                    r = parse(raw, is_known)
                except ET.ParseError:
                    continue
                # unknown iDs: keep the whole record (career context) only if an affiliation itself mentions sociology
                if not is_known:
                    r = [x for x in r if any(SOC.search((x[k] or "").encode()) for k in ("department", "role", "organization"))] and r
                if r:
                    rows.extend(r)
                    kept += 1
            if seen % 200_000 == 0:
                print(f"  {seen:,} records read, {kept:,} kept ({time.time() - t0:,.0f}s)", flush=True)
                pd.DataFrame(rows).to_parquet(OUT, index=False)  # checkpoint
            if limit and seen >= limit:
                break
    pd.DataFrame(rows).to_parquet(OUT, index=False)
    print(f"done: {seen:,} records read, {kept:,} kept, {len(rows):,} affiliation rows -> {OUT}")


if __name__ == "__main__":
    main()
