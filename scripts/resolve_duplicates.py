"""Find people who appear twice and decide which pairs to merge.

Runs on the current explorer export (explorer/data/lineage.json), so it sees AFT people and the
people added from outside sources (pid >= 900_000_000) together.

Candidate pairs share a surname and have compatible first names (equal, or one is an initial or
prefix of the other, with no conflicting middle initials). Evidence:
  shared  - they share an advisor or a student        (strong)
  inst    - their institutions share a distinctive word
  years   - estimated PhD years within 2 years

Auto-merge (data/external/person_merges.csv):
  * an outside-source person + an AFT person: shared neighbour, or institution + full first name
  * two AFT people: same first name (full, not an initial) + shared neighbour or institution
Everything else with some evidence goes to data/external/duplicate_review.csv for a human.
The AFT record is always kept; between two AFT records, the one with more links is kept.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys; _sys.path.insert(0, str(ROOT / "scripts"))
from field import WORK, EXPL, DOCS, FIELD, CFG, AUTHORPUB  # noqa: E402,F401
EXT = WORK / "data" / "external"
LIN = EXPL / "lineage.json"
EXT_BASE = 900_000_000
SUFFIX = {"jr", "sr", "ii", "iii", "iv", "phd"}
STOP = {"university", "of", "the", "at", "college", "and", "state", "institute", "de", "la", "du", "school", "new"}


def toks(s):
    s = unicodedata.normalize("NFKD", s if isinstance(s, str) else "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return [t for t in re.split(r"[^a-z]+", s) if t and t not in SUFFIX]


def compatible(a: list[str], b: list[str]) -> tuple[bool, bool]:
    """(compatible, full_first_name_equal). a/b are given-name tokens (first + middles)."""
    if not a or not b:
        return False, False
    fa, fb = a[0], b[0]
    if not (fa.startswith(fb) or fb.startswith(fa)):
        return False, False
    if len(fa) > 1 and len(fb) > 1 and fa != fb and min(len(fa), len(fb)) < 3:
        return False, False  # "Jo" vs "Joshua"
    ma, mb = a[1:2], b[1:2]  # middle initials must not conflict
    if ma and mb and ma[0][0] != mb[0][0]:
        return False, False
    return True, fa == fb and len(fa) > 1


def main() -> None:
    d = json.loads(LIN.read_text())
    people = {r[0]: {"name": r[1], "inst": r[2], "nd": r[5], "deg": r[4] + r[6], "phd": r[12] if len(r) > 12 else None}
              for r in d["people"]}
    nbrs = defaultdict(set)
    for m, t, *_ in d["edges"]:
        nbrs[m].add(t)
        nbrs[t].add(m)
    groups = defaultdict(list)
    for pid, p in people.items():
        t = toks(p["name"])
        if len(t) >= 2:
            p["given"], p["last"] = t[:-1], t[-1]
            p["iw"] = {w for w in toks(p["inst"]) if w not in STOP and len(w) > 2}
            groups[(t[-1], t[0][0])].append(pid)

    merges, review = [], []
    for ids in groups.values():
        if len(ids) < 2 or len(ids) > 60:
            continue
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                A, B = people[a], people[b]
                ok, full_eq = compatible(A["given"], B["given"])
                if not ok:
                    continue
                shared = bool(nbrs[a] & nbrs[b])
                inst = bool(A["iw"] & B["iw"])
                years = A["phd"] is not None and B["phd"] is not None and abs(A["phd"] - B["phd"]) <= 2
                linked = b in nbrs[a]  # an advisor/student pair is never the same person
                if linked or not (shared or inst or years):
                    continue
                ext_a, ext_b = a >= EXT_BASE, b >= EXT_BASE
                same_full = toks(A["name"]) == toks(B["name"])
                reason = "+".join(k for k, v in (("shared", shared), ("inst", inst), ("years", years)) if v)
                if ext_a != ext_b and (shared or (inst and full_eq)):
                    keep, drop = (b, a) if ext_a else (a, b)
                    merges.append((drop, keep, reason))
                elif not ext_a and not ext_b and (same_full or full_eq or "".join(A["given"]) == "".join(B["given"])) and (shared or inst):
                    # two AFT records: same first name (or same name spelled with/without spaces/hyphens)
                    # plus a shared advisor/student or institution
                    keep, drop = (a, b) if A["deg"] >= B["deg"] else (b, a)
                    merges.append((drop, keep, reason))
                elif ext_a and ext_b:
                    continue  # two outside records: merge_external already unified identical names
                elif shared or inst:  # a close PhD year alone is too weak to show a human
                    review.append({"pid_a": a, "name_a": A["name"], "inst_a": A["inst"], "pid_b": b,
                                   "name_b": B["name"], "inst_b": B["inst"], "evidence": reason})

    # one record can only be dropped once; resolve chains to the final kept id
    to = {}
    for drop, keep, reason in sorted(merges, key=lambda x: -len(x[2])):
        if drop not in to and keep not in to:
            to[drop] = (keep, reason)
    rows = [{"drop_pid": k, "keep_pid": v[0], "reason": v[1], "drop_name": people[k]["name"], "keep_name": people[v[0]]["name"]}
            for k, v in to.items()]
    pd.DataFrame(rows).to_csv(EXT / "person_merges.csv", index=False)
    pd.DataFrame(review).to_csv(EXT / "duplicate_review.csv", index=False)
    m = pd.DataFrame(rows)
    print(f"auto-merges: {len(rows)}  ({(m.drop_pid >= EXT_BASE).sum() if len(m) else 0} outside-source into AFT)")
    print(f"for review:  {len(review)}")
    if len(m):
        print(m.sample(min(12, len(m)), random_state=2)[["drop_name", "keep_name", "reason"]].to_string(index=False))


if __name__ == "__main__":
    main()
