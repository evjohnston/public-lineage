"""Fetch education and employment for ORCID iDs we know but the bulk extract didn't keep.

The bulk summaries pass (extract_orcid_summaries.py) kept sociology-related records and the iDs
known at that time. iDs learned later (from OpenAlex author profiles) are fetched here from the
ORCID public API with the client credentials in .env, then appended to
data/external/orcid_affiliations.parquet in the same columns (known = True).
Usage: python -I scripts/fetch_orcid_api.py
"""

import time
from pathlib import Path

import httpx
import pandas as pd
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"
AFF = EXT / "orcid_affiliations.parquet"
ENV = dotenv_values(ROOT / ".env")
UA = {"User-Agent": "academic-lineage-research/0.1", "Accept": "application/json"}


def token():
    r = httpx.post("https://orcid.org/oauth/token", data={
        "client_id": ENV["ORCID_CLIENT_ID"], "client_secret": ENV["ORCID_CLIENT_SECRET"],
        "grant_type": "client_credentials", "scope": "/read-public"}, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def year(d, k):
    v = ((d or {}).get(k) or {}).get("year") or {}
    v = v.get("value") if isinstance(v, dict) else None
    return int(v) if v and str(v).isdigit() else None


def main():
    aff = pd.read_parquet(AFF)
    have = set(aff.orcid)
    oa = pd.read_parquet(EXT / "openalex_authors.parquet")
    want = sorted({o for o in oa.orcid.dropna() if o not in have})
    print(f"{len(want):,} ORCID iDs to fetch", flush=True)
    H = {**UA, "Authorization": f"Bearer {token()}"}
    rows = []
    with httpx.Client(headers=H, timeout=40) as c:
        for n, o in enumerate(want, 1):
            for attempt in range(5):
                try:
                    r = c.get(f"https://pub.orcid.org/v3.0/{o}/record")
                except httpx.HTTPError:
                    time.sleep(2 ** attempt); continue
                if r.status_code in (429, 500, 502, 503):
                    time.sleep(2 ** attempt); continue
                break
            else:
                continue
            if r.status_code != 200:
                continue
            rec = r.json()
            name = ((rec.get("person") or {}).get("name") or {})
            given = ((name.get("given-names") or {}).get("value"))
            family = ((name.get("family-name") or {}).get("value"))
            acts = rec.get("activities-summary") or {}
            for kind in ("education", "employment"):
                for grp in ((acts.get(f"{kind}s") or {}).get("affiliation-group") or []):
                    for s in grp.get("summaries") or []:
                        x = s.get(f"{kind}-summary") or {}
                        org = x.get("organization") or {}
                        addr = org.get("address") or {}
                        rows.append({"orcid": o, "given_names": given, "family_name": family, "kind": kind,
                                     "organization": org.get("name"), "city": addr.get("city"), "country": addr.get("country"),
                                     "department": x.get("department-name"), "role": x.get("role-title"),
                                     "start_year": year(x, "start-date"), "end_year": year(x, "end-date"), "known": True})
            if n % 500 == 0 or n == len(want):
                print(f"  {n:,}/{len(want):,}, {len(rows):,} rows", flush=True)
            time.sleep(0.06)  # well under the public API's limits
    new = pd.DataFrame(rows)
    if len(new):
        pd.concat([aff, new], ignore_index=True).to_parquet(AFF, index=False)
    print(f"appended {len(new):,} rows for {new.orcid.nunique() if len(new) else 0:,} iDs")


if __name__ == "__main__":
    main()
