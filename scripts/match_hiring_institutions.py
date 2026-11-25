"""Map faculty-hiring institution names (short forms like "Penn State", "UNC") to AFT locids.

Writes data/external/faculty_hiring_inst_map.parquet: hiring_id, hiring_name, locid, aft_name, method.
Unmatched institutions keep locid = null and are reported, never guessed.
"""

import re
import sys
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"
DB = Path(sys.argv[sys.argv.index("--db") + 1]) if "--db" in sys.argv else ROOT / "data" / "lineage.duckdb"

ALIASES = {
    "penn state": "pennsylvania state university", "unc": "university of north carolina chapel hill",
    "lsu": "louisiana state university", "ut austin": "university of texas austin",
    "cu boulder": "university of colorado boulder", "cu denver": "university of colorado denver",
    "iupui": "indiana university purdue university indianapolis", "nyu": "new york university",
    "usc": "university of southern california", "ucla": "university of california los angeles",
    "umass amherst": "university of massachusetts amherst", "suny albany": "state university of new york albany",
    "uic": "university of illinois chicago", "uiuc": "university of illinois urbana champaign",
    "mit": "massachusetts institute of technology", "byu": "brigham young university",
    "university of wisconsin-madison": "university of wisconsin madison",
    "city university of new york, the": "city university of new york",
    "graduate school and university center (cuny)": "graduate school and university center",
    "ecole des hautes etudes": "ecole des hautes etudes en sciences sociales",
    "american": "american university", "howard": "howard university", "drew": "drew university",
    "clark": "clark university", "barry": "barry university",
    "uw": "university of washington", "upenn": "university of pennsylvania", "uconn": "university of connecticut",
    "washington university st. louis": "washington university", "suny stony brook": "stony brook",
    "unc charlotte": "university of north carolina charlotte", "university at albany (suny)": "albany",
    "virginia tech": "virginia polytechnic institute", "dartmouth": "dartmouth college",
    "max planck institute": None,  # a family of institutes; no single match
    "university of barcelona": None,  # AFT only has the Autonomous University, a different school
}
DROP = {"the", "at", "in"}


def toks(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " and ")
    return [t for t in re.split(r"[^a-z]+", s) if t]


def expand(name):
    n = name.strip().lower()
    if n in ALIASES:
        return ALIASES[n]
    for pre, full in (("uc ", "university of california "), ("ut ", "university of texas "), ("umass ", "university of massachusetts ")):
        if n.startswith(pre):
            return full + n[len(pre):]
    return n


def contains_run(hay, needle):
    """needle's words appear in hay contiguously and in order"""
    k = len(needle)
    return any(hay[i:i + k] == needle for i in range(len(hay) - k + 1))


def main():
    f = pd.read_parquet(EXT / "faculty_hiring_sociology_flows.parquet")
    hi = pd.concat([f[["phd_institution_id", "phd_institution"]].set_axis(["id", "name"], axis=1),
                    f[["hiring_institution_id", "hiring_institution"]].set_axis(["id", "name"], axis=1)]).drop_duplicates("id")
    con = duckdb.connect(str(DB), read_only=True)
    locs = con.execute("""
        SELECT l.locid, l.location, count(m.cid) AS phds
        FROM aft_locations l LEFT JOIN aft_mentorship m ON m.locid = l.locid
        GROUP BY 1, 2""").fetchall()
    seq = lambda x: [t for t in toks(x) if t not in DROP]
    cands = [(locid, loc, phds, seq(loc)) for locid, loc, phds in locs if loc]
    exact = {}
    for locid, loc, phds, sq in sorted(cands, key=lambda c: c[2]):
        exact[" ".join(sq)] = locid  # most PhDs wins on identical names

    rows = []
    for r in hi.itertuples(index=False):
        target = expand(r.name)
        if target is None:
            locid, method = None, "unmatched"
        else:
            want = seq(target)
            locid, method = exact.get(" ".join(want)), "exact"
            if locid is None and want:
                # the hiring name's words must appear in order inside the AFT name
                # ("University of Michigan" never matches "Michigan State University")
                hits = [c for c in cands if contains_run(c[3], want)]
                hits.sort(key=lambda c: (len(c[3]) - len(want), -c[2]))
                if hits and (len(hits) == 1 or len(hits[0][3]) < len(hits[1][3]) or hits[0][2] > 3 * max(hits[1][2], 1)):
                    locid, method = hits[0][0], "in-order"
        name = next((c[1] for c in cands if c[0] == locid), None)
        rows.append({"hiring_id": int(r.id), "hiring_name": r.name, "locid": locid, "aft_name": name,
                     "method": method if locid is not None else "unmatched"})
    out = pd.DataFrame(rows)
    out.to_parquet(EXT / "faculty_hiring_inst_map.parquet", index=False)
    print(out.method.value_counts().to_dict())
    w = f.merge(out[["hiring_id", "locid"]], left_on="phd_institution_id", right_on="hiring_id", how="left")
    print("faculty covered by matched PhD institution:", int(w[w.locid.notna()].n.sum()), "of", int(f.n.sum()))
    print("token matches (check):")
    print(out[out.method == "in-order"][["hiring_name", "aft_name"]].to_string(index=False))
    print("unmatched:", ", ".join(out[out.method == "unmatched"].hiring_name.tolist()))


if __name__ == "__main__":
    main()
