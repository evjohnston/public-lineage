"""Turn reviewed candidate links into data the build merges.

Review files (data/review/), one row per candidate, with an "accept" column you fill in:
  advisor_research.csv        advisors found by searching sources (obituaries, Wikipedia, theses.fr ...)
  wikidata_name_matches.csv   Wikidata doctoral advisors of roots matched by name (match_wikidata_names.py)
  edge_corrections.csv        links in the data that look wrong: action remove or reverse
Mark accept = yes for the rows you agree with (blank or anything else = not accepted). Then:
  python -I scripts/apply_reviews.py            -> data/manual_edges_reviewed.csv  (merged as source "manual")
                                                -> data/known_roots.csv            (people with no doctoral advisor)
                                                -> data/edge_corrections.csv       (links to remove or reverse)
  sh scripts/build_all.sh

  python -I scripts/apply_reviews.py --collect DIR   builds advisor_research.csv from research result*.json
                                                     files, keeping any accept marks already made.
"""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "review"
YES = {"yes", "y", "x", "1", "true", "accept"}
COLS = ["advisor_pid", "advisor_name", "student_pid", "student_name", "year", "institution", "url", "note", "role", "degree"]
# why someone has no doctoral advisor (known_roots*.csv "reason")
REASONS = {"published_work": "degree awarded for a published work", "honorary": "honorary degree only",
           "unfinished": "never completed a doctorate", "no_director": "no thesis director in that system",
           "no_doctorate": "no doctorate"}


def guess_reason(text):
    t = (text or "").lower()
    if "honorary" in t: return "honorary"
    if "never" in t or "did not complete" in t or "not finish" in t: return "unfinished"
    if "ba and an ma" in t or "no phd" in t or "no doctorate" in t or "never earned" in t: return "no_doctorate"
    if "published" in t or "book" in t: return "published_work"
    return "no_director"


def collect(src: Path):
    rows = []
    for f in sorted(src.glob("result*.json")):
        for r in json.loads(f.read_text()):
            base = {"student_pid": r["pid"], "student_name": r["name"], "status": r.get("status"),
                    "phd_institution": r.get("phd_institution"), "phd_year": r.get("phd_year"),
                    "source_url": r.get("source_url"), "evidence": r.get("evidence"),
                    "confidence": r.get("confidence"), "notes": r.get("notes")}
            if r.get("status") == "advisor_found":
                for a in r.get("advisors") or []:
                    rows.append({"accept": "", "suggest": "accept" if r.get("confidence") == "high" and r.get("source_url") else "check",
                                 "advisor_name": a, "role": "director", **base})
            elif r.get("status") == "no_doctoral_advisor":
                rows.append({"accept": "", "suggest": "accept" if r.get("source_url") else "check", "advisor_name": "",
                             "reason": guess_reason(f"{r.get('notes') or ''} {r.get('evidence') or ''}"), **base})
            else:
                rows.append({"accept": "", "suggest": "none", "advisor_name": "", **base})
    df = pd.DataFrame(rows)
    out = REVIEW / "advisor_research.csv"
    if out.exists():  # keep marks already made
        old = pd.read_csv(out, dtype=str).fillna("")
        keep = {(o.student_pid, o.advisor_name): o.accept for o in old.itertuples(index=False) if o.accept}
        df["accept"] = [keep.get((str(r.student_pid), r.advisor_name or ""), "") for r in df.itertuples(index=False)]
    order = {"accept": 0, "check": 1, "none": 2}
    df = df.sort_values("suggest", key=lambda c: c.map(order), kind="stable")
    REVIEW.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"wrote {len(df)} rows to {out.relative_to(ROOT)}:", df.groupby(["status", "suggest"]).size().to_dict())


def apply():
    edges, roots = [], []
    pid_of_q = {}
    me = ROOT / "data" / "external" / "merged_edges.parquet"
    if me.exists():
        for r in pd.read_parquet(me).itertuples(index=False):
            if r.source == "wikidata" and "-" in str(r.source_id):
                aq, sq = str(r.source_id).split("-", 1)
                pid_of_q[aq], pid_of_q[sq] = int(r.advisor_pid), int(r.student_pid)
    f = REVIEW / "advisor_research.csv"
    if f.exists():
        d = pd.read_csv(f, dtype=str).fillna("")
        for r in d[d.accept.str.strip().str.lower().isin(YES)].itertuples(index=False):
            if r.status == "advisor_found" and r.advisor_name:
                edges.append({"advisor_pid": "", "advisor_name": r.advisor_name, "student_pid": r.student_pid, "student_name": r.student_name,
                              "year": r.phd_year.split(".")[0], "institution": r.phd_institution, "url": r.source_url,
                              "note": f"reviewed research: {r.evidence}"[:300], "role": (getattr(r, "role", "") or "director"), "degree": ""})
            elif r.status == "no_doctoral_advisor":
                roots.append({"pid": r.student_pid, "name": r.student_name, "url": r.source_url, "evidence": r.evidence, "reason": getattr(r, "reason", "") or "no_director"})
    f = REVIEW / "wikidata_name_matches.csv"
    if f.exists():
        d = pd.read_csv(f, dtype=str).fillna("")
        for r in d[d.accept.str.strip().str.lower().isin(YES)].itertuples(index=False):
            edges.append({"advisor_pid": str(pid_of_q.get(r.advisor_qid, "")), "advisor_name": r.advisor_name, "student_pid": r.student_pid,
                          "student_name": r.student_name, "year": "", "institution": r.student_institution, "url": r.url,
                          "note": f"reviewed Wikidata name match {r.wikidata_person} -> {r.advisor_qid}", "role": "director", "degree": ""})
    fixes = []
    f = REVIEW / "edge_corrections.csv"
    if f.exists():
        d = pd.read_csv(f, dtype=str).fillna("")
        for r in d[d.accept.str.strip().str.lower().isin(YES)].itertuples(index=False):
            fixes.append({"action": r.action, "advisor_pid": r.advisor_pid, "student_pid": r.student_pid, "reason": r.reason, "url": r.url})
    pd.DataFrame(fixes, columns=["action", "advisor_pid", "student_pid", "reason", "url"]).to_csv(ROOT / "data" / "edge_corrections.csv", index=False)
    pd.DataFrame(edges, columns=COLS).to_csv(ROOT / "data" / "manual_edges_reviewed.csv", index=False)
    pd.DataFrame(roots, columns=["pid", "name", "url", "evidence", "reason"]).to_csv(ROOT / "data" / "known_roots.csv", index=False)
    print(f"{len(edges)} accepted advisor links -> data/manual_edges_reviewed.csv; {len(roots)} confirmed founders -> data/known_roots.csv; "
          f"{len(fixes)} link corrections -> data/edge_corrections.csv")


if __name__ == "__main__":
    if "--collect" in sys.argv:
        collect(Path(sys.argv[sys.argv.index("--collect") + 1]))
    else:
        apply()
