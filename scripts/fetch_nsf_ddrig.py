"""Fetch NSF Sociology Doctoral Dissertation Research Improvement Grants (DDRIGs)
from the public NSF Award Search API and turn them into advisor -> student edges.

In Sociology DDRIGs the faculty advisor is normally the PI and the doctoral
student is listed as co-PI, so each (PI, co-PI) pair becomes one edge.

Query strategy
--------------
* ``fundProgramName=SOCIOLOGY`` (word match; also catches "Sociology, X" combos
  and "Sociology DDRI"), partitioned by award start-date windows because the API
  caps any query at 3,000 results and its ordering is not stable across pages.
  If a window returns fewer unique ids than ``totalCount`` it is split in half
  and re-fetched.
* Client-side filter: title mentions "dissertation" (Doctoral Dissertation
  Research / Dissertation Research / Doctoral Dissertation Improvement ...) and
  the award is managed by, or carries, Sociology program element 1331
  (``133100``). The ASA-run DDRIG umbrella awards are excluded.

Raw JSON pages are cached under data/raw/nsf/ so reruns are offline/cheap.
Output: data/external/nsf_ddrig_edges.parquet

Usage: .venv/bin/python scripts/fetch_nsf_ddrig.py [--refresh]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "nsf"
OUT = ROOT / "data" / "external" / "nsf_ddrig_edges.parquet"
AWARDS_OUT = RAW_DIR / "sociology_ddrig_awards.json"

API = "https://api.nsf.gov/services/v1/awards.json"
UA = "academic-lineage-research/0.1"
RPP = 25  # documented maximum
PRINT_FIELDS = (
    "id,title,piFirstName,piMiddeInitial,piLastName,pdPIName,coPDPI,awardeeName,"
    "startDate,fundProgramName,progEleCode,managingPec,progRefCode,estimatedTotalAmt"
)
FIRST_YEAR, LAST_YEAR = 1970, dt.date.today().year + 1
SLEEP = 0.6

# "doctoral dis..." catches misspellings such as "Dissertaton", "Disseration"
DISS_RE = re.compile(r"dissertation|\bDDRI|\bdoctoral\s+dis", re.I)
ASA_RE = re.compile(r"American Sociological Association|ASA DDRIG", re.I)
EMAIL_RE = re.compile(r"\S+@\S+")
FORMER_RE = re.compile(r"\(\s*former\s*\)", re.I)


class Client:
    def __init__(self, refresh: bool = False):
        self.http = httpx.Client(headers={"User-Agent": UA}, timeout=60)
        self.refresh = refresh
        self.n_requests = 0
        self._last = 0.0

    def get(self, params: dict) -> dict:
        key = urlencode(sorted(params.items()))
        fname = hashlib.sha1(key.encode()).hexdigest()[:16] + ".json"
        path = RAW_DIR / "pages" / fname
        if path.exists() and not self.refresh:
            return json.loads(path.read_text())["data"]
        for attempt in range(5):
            wait = SLEEP - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                r = self.http.get(API, params=params)
                self.n_requests += 1
                r.raise_for_status()
                data = r.json()
                break
            except (httpx.HTTPError, ValueError) as e:
                print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"failed: {params}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"params": params, "data": data}))
        return data


def fmt(d: dt.date) -> str:
    return d.strftime("%m/%d/%Y")


def fetch_window(cl: Client, base: dict, start: dt.date, end: dt.date, depth=0) -> dict:
    """Fetch all awards with startDate in [start, end]; split window if paging is lossy."""
    params = {**base, "startDateStart": fmt(start), "startDateEnd": fmt(end), "rpp": RPP}
    first = cl.get({**params, "offset": 0})["response"]
    total = int(first.get("metadata", {}).get("totalCount", 0))
    awards = {a["id"]: a for a in first.get("award", [])}
    for off in range(RPP, total, RPP):
        page = cl.get({**params, "offset": off})["response"]
        for a in page.get("award", []):
            awards[a["id"]] = a
    span = (end - start).days
    if len(awards) < total and span > 0:
        mid = start + dt.timedelta(days=span // 2)
        print(f"{'  ' * depth}{start}..{end}: {len(awards)}/{total} unique -> split")
        out = fetch_window(cl, base, start, mid, depth + 1)
        out.update(fetch_window(cl, base, mid + dt.timedelta(days=1), end, depth + 1))
        return out
    if total:
        print(f"{'  ' * depth}{start}..{end}: {len(awards)}/{total}")
    return awards


def is_sociology(a: dict) -> bool:
    codes = (a.get("progEleCode") or "") + "," + (a.get("managingPec") or "")
    return "133100" in codes or "sociology" in (a.get("fundProgramName") or "").lower()


def is_ddrig(a: dict) -> bool:
    t = a.get("title") or ""
    return bool(DISS_RE.search(t)) and not ASA_RE.search(t)


def clean_name(s: str) -> tuple[str, bool]:
    former = bool(FORMER_RE.search(s))
    s = FORMER_RE.sub(" ", EMAIL_RE.sub(" ", s))
    s = re.sub(r"\b\d[\d\-() ]{6,}\d\b", " ", s)  # stray phone numbers
    return re.sub(r"\s+", " ", s).strip(), former


def pi_name(a: dict) -> str:
    if a.get("pdPIName"):
        return re.sub(r"\s+", " ", a["pdPIName"]).strip()
    parts = [a.get("piFirstName"), a.get("piMiddeInitial"), a.get("piLastName")]
    return " ".join(p for p in parts if p).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore cached pages")
    args = ap.parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cl = Client(refresh=args.refresh)

    base = {"fundProgramName": "SOCIOLOGY", "printFields": PRINT_FIELDS}
    awards: dict[str, dict] = {}
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        awards.update(fetch_window(cl, base, dt.date(y, 1, 1), dt.date(y, 12, 31)))
    print(f"sociology-fund awards: {len(awards)} ({cl.n_requests} API requests)")

    ddrig = {k: a for k, a in awards.items() if is_sociology(a) and is_ddrig(a)}
    AWARDS_OUT.write_text(json.dumps(sorted(ddrig.values(), key=lambda a: a["id"]), indent=1))

    rows, no_copi = [], []
    for aid, a in sorted(ddrig.items()):
        copis = a.get("coPDPI") or []
        if isinstance(copis, str):
            copis = [copis]
        year = int(a["startDate"][-4:]) if a.get("startDate") else None
        if not copis:
            no_copi.append(aid)
            continue
        advisor = pi_name(a)
        for c in copis:
            name, former = clean_name(c)
            if not name or name.lower() == advisor.lower():
                continue  # e.g. a former PI who was moved to the co-PI slot
            rows.append(
                dict(
                    source="nsf_ddrig",
                    source_id=aid,
                    advisor_name=advisor,
                    student_name=name,
                    year=year,
                    institution=a.get("awardeeName"),
                    field="sociology",
                    url=f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={aid}",
                    title=re.sub(r"\s+", " ", a.get("title") or "").strip(),
                    copi_former=former,
                    n_copi=len(copis),
                )
            )
    df = pd.DataFrame(rows)
    df["year"] = df["year"].astype("Int64")
    # Quality flags. Before ~2008 the co-PI slot was rarely used for the student,
    # and when an award has several co-PIs, one is often a faculty co-advisor.
    # A co-PI who is the PI (advisor) of some Sociology DDRIG by the same year
    # is almost certainly faculty, not the student.
    first_pi_year = df.groupby(df["advisor_name"].str.lower())["year"].min()
    df["copi_is_advisor_elsewhere"] = [
        (y0 := first_pi_year.get(s.lower())) is not None and y0 <= y + 1
        for s, y in zip(df["student_name"], df["year"])
    ]
    df["confidence"] = "high"
    df.loc[(df["year"] < 2008) | (df["n_copi"] > 1) | df["copi_former"], "confidence"] = "medium"
    df.loc[df["copi_is_advisor_elsewhere"], "confidence"] = "low"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)

    yrs = [int(a["startDate"][-4:]) for a in ddrig.values() if a.get("startDate")]
    print(f"DDRIG awards: {len(ddrig)}  years {min(yrs)}-{max(yrs)}")
    print(f"with co-PI: {len(ddrig) - len(no_copi)}  without co-PI (excluded): {len(no_copi)}")
    print(f"edges written: {len(df)} -> {OUT}")
    print(df["confidence"].value_counts().to_string())


if __name__ == "__main__":
    main()
