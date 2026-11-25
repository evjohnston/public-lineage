"""First-pass analyses of the sociology lineage network.

Reads the cleaned, merged exports (explorer/data/lineage.json, context.json) and the faculty hiring
census, writes figures to docs/analysis/figs/ and numbers to docs/analysis/results.json.

  A1  Placement concentration: how concentrated is US sociology faculty production?
  A2  Fecundity transmission: do advisors with many students produce students with many students?
  A3  Subfield inheritance: do students share their advisor's subfield beyond cohort chance?
  A4  Schools over time: what share of each decade's PhDs descend from each curated school?

Usage: python -I scripts/analysis/run_analyses.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy import stats

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "analysis"
FIGS = OUT / "figs"
FIGS.mkdir(parents=True, exist_ok=True)
RNG = np.random.default_rng(7)
INK, INK3, RULE, RED = "#161616", "#6a6a67", "#e9e6df", "#c8102e"
F_OUTSIDE = 1

# static Source Sans 3 cuts (the system variable font renders as ExtraLight in matplotlib)
for f in (Path(__file__).parent / "fonts").glob("SourceSans3-*.ttf"):
    font_manager.fontManager.addfont(str(f))
plt.rcParams.update({
    "font.family": ["Source Sans 3", "DejaVu Sans"], "font.size": 10.5, "axes.edgecolor": INK3,
    "axes.labelcolor": INK, "xtick.color": INK3, "ytick.color": INK3, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": RULE, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "figure.dpi": 100, "savefig.dpi": 200, "savefig.bbox": "tight",
    "axes.titleweight": 700, "axes.titlesize": 12, "axes.titlelocation": "left",
})


def load():
    lin = json.loads((ROOT / "explorer" / "data" / "lineage.json").read_text())
    ctx = json.loads((ROOT / "explorer" / "data" / "context.json").read_text())
    people = {r[0]: {"name": r[1], "f": r[3], "ns": r[4], "nd": r[5], "phd": r[12] if len(r) > 12 else None}
              for r in lin["people"]}
    phd_edges = [(m, t) for m, t, rel, *_ in lin["edges"] if rel == 1 and m in people and t in people]
    all_edges = [(m, t) for m, t, *_ in lin["edges"] if m in people and t in people]
    return lin, ctx, people, phd_edges, all_edges


# ------------------------------------------------------------------ A1 placement concentration
def a1(res):
    fl = pd.read_parquet(ROOT / "data" / "external" / "faculty_hiring_sociology_flows.parquet")
    total = int(fl.n.sum())
    prod = fl.groupby("phd_institution").n.sum().sort_values(ascending=False)
    share = lambda k: float(prod.head(k).sum() / total)
    x = np.sort(prod.values)
    lor = np.concatenate([[0], np.cumsum(x) / x.sum()])
    gini = float(1 - 2 * np.trapezoid(lor, dx=1 / len(x)))
    ranked = fl.dropna(subset=["phd_ordinal_prestige_rank", "hiring_ordinal_prestige_rank"])
    moves = ranked[~ranked.self_hire]
    down = float(moves[moves.phd_ordinal_prestige_rank < moves.hiring_ordinal_prestige_rank].n.sum() / moves.n.sum())
    up = float(moves[moves.phd_ordinal_prestige_rank > moves.hiring_ordinal_prestige_rank].n.sum() / moves.n.sum())
    self_rate = float(fl[fl.self_hire].n.sum() / total)
    res["A1"] = {"faculty": total, "phd_institutions": int(len(prod)), "top5_share": share(5), "top10_share": share(10),
                 "top20_share": share(20), "gini": gini, "moves_down": down, "moves_up": up, "self_hire_rate": self_rate,
                 "top10": [[k, int(v)] for k, v in prod.head(10).items()]}

    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    xs = np.linspace(0, 1, len(lor))
    # Lorenz curve read from the top: share of faculty trained at the top X% of PhD programs
    top_frac = 1 - xs[::-1]
    ax.plot(top_frac, 1 - lor[::-1], color=INK, lw=2)
    ax.plot([0, 1], [0, 1], color=INK3, lw=1, ls=(0, (2, 3)))
    k = int(np.ceil(0.1 * len(x)))
    y10 = float(prod.head(k).sum() / total)
    ax.scatter([0.1], [y10], s=36, color=RED, zorder=3)
    ax.annotate(f"top 10% of programs\ntrained {y10:.0%} of faculty", (0.1, y10), xytext=(0.22, y10 - 0.18),
                color=INK, fontsize=10, arrowprops={"arrowstyle": "-", "color": INK3, "lw": 0.8})
    ax.text(0.62, 0.52, "equal production", color=INK3, fontsize=9.5, rotation=35)
    ax.set_xlabel("Share of PhD-granting programs, most productive first")
    ax.set_ylabel("Share of US sociology faculty trained")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1)); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1))
    ax.set_title("A few programs train most US sociology faculty")
    fig.text(0, -0.09, f"US sociology faculty 2011–20 (n = {total:,}), by PhD institution. Source: Wapman et al., Nature 2022.", color=INK3, fontsize=8.5)
    fig.savefig(FIGS / "a1_concentration.png"); plt.close(fig)


# ------------------------------------------------------------------ A2 fecundity transmission
def a2(res, people, phd_edges):
    rows = []
    for a, s in phd_edges:
        A, S = people[a], people[s]
        # dated PhDs are almost all 2000-2014 (ProQuest-era records); use one coherent window with
        # 16+ years before the 2022 snapshot for students to have advised students of their own
        if A["f"] & F_OUTSIDE or S["f"] & F_OUTSIDE or not S["phd"] or not 2000 <= S["phd"] <= 2006:
            continue
        rows.append({"adv": a, "adv_students": A["ns"] - 1, "stu_students": S["ns"], "decade": S["phd"]})  # stratum = PhD year
    df = pd.DataFrame(rows)
    rho, _ = stats.spearmanr(df.adv_students, df.stu_students)
    groups = [g.index.values for _, g in df.groupby("decade")]
    x, y = df.adv_students.values, df.stu_students.values

    def within_rho(yv):
        # cohort-adjusted statistic: Spearman within each PhD decade, weighted by pairs
        num = den = 0.0
        for idx in groups:
            if len(idx) >= 30 and np.ptp(x[idx]) and np.ptp(yv[idx]):
                num += len(idx) * stats.spearmanr(x[idx], yv[idx])[0]
                den += len(idx)
        return num / den

    w_obs = within_rho(y)
    null_overall, null_within = [], []
    for _ in range(500):
        yy = y.copy()
        for idx in groups:
            yy[idx] = RNG.permutation(yy[idx])
        null_overall.append(stats.spearmanr(x, yy)[0])
        null_within.append(within_rho(yy))
    p = float((np.sum(np.abs(null_within) >= abs(w_obs)) + 1) / (len(null_within) + 1))
    within = {int(d): float(stats.spearmanr(g.adv_students, g.stu_students)[0]) for d, g in df.groupby("decade") if len(g) >= 50}
    # outcomes relative to the student's own cohort, so cohort timing can't drive the chart
    df["rel"] = df.stu_students - df.groupby("decade").stu_students.transform("mean")
    bins = [(-1, 0, "0"), (1, 4, "1–4"), (5, 9, "5–9"), (10, 19, "10–19"), (20, 10**6, "20+")]
    summ = []
    for lo, hi, lab in bins:
        g = df[(df.adv_students >= lo) & (df.adv_students <= hi)]
        if not len(g):
            continue
        boots = [RNG.choice(g.rel.values, len(g)).mean() for _ in range(1000)]
        summ.append({"bin": lab, "n": int(len(g)), "mean": float(g.rel.mean()), "lo": float(np.percentile(boots, 2.5)),
                     "hi": float(np.percentile(boots, 97.5)), "raw_mean": float(g.stu_students.mean()),
                     "share_any": float((g.stu_students > 0).mean())})
    res["A2"] = {"pairs": int(len(df)), "spearman_rho": float(rho), "null_overall_rho_mean": float(np.mean(null_overall)),
                 "within_decade_rho": float(w_obs), "within_perm_p": p, "rho_by_decade": within, "bins": summ}

    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    xs = np.arange(len(summ))
    ax.errorbar(xs, [b["mean"] for b in summ], yerr=[[b["mean"] - b["lo"] for b in summ], [b["hi"] - b["mean"] for b in summ]],
                fmt="o", color=INK, ms=7, lw=1.4, capsize=0)
    ax.axhline(0, color=INK3, lw=1)
    for i, b in enumerate(summ):
        ax.text(i, b["hi"] + 0.02, f"n={b['n']:,}", ha="center", color=INK3, fontsize=8.5)
    ax.set_xticks(xs, [b["bin"] for b in summ])
    ax.set_xlabel("Advisor's other PhD students")
    ax.set_ylabel("Student's own students vs. cohort average")
    lo = min(b["lo"] for b in summ); hi = max(b["hi"] for b in summ)
    ax.set_ylim(lo - 0.08, hi + 0.12)
    ax.set_title("Only students of the most prolific advisors go on to advise more")
    fig.text(0, -0.13, f"Sociology advisor–student pairs, student PhD 2000–06 (n = {len(df):,}); outcome minus the mean of the student's PhD year, 95% CI.\n"
             f"Cohort-adjusted Spearman ρ = {w_obs:.2f} (within-year permutation p = {p:.3f}); unadjusted ρ = {rho:.2f}. Sources: AFT, NSF, Wikidata.",
             color=INK3, fontsize=8.5)
    fig.savefig(FIGS / "a2_fecundity.png"); plt.close(fig)


# ------------------------------------------------------------------ A3 subfield inheritance
def a3(res, ctx, people, phd_edges):
    sf = {int(k): set(v[4]) for k, v in ctx["person"].items() if v[4]}
    names = [s["name"] for s in ctx["subfields"]]
    pairs = [(a, s, (people[s]["phd"] or 0) // 10 * 10) for a, s in phd_edges if a in sf and s in sf]
    df = pd.DataFrame(pairs, columns=["a", "s", "decade"])
    stu = df.s.values
    groups = [g.index.values for _, g in df.groupby("decade")]

    def rates(students):
        hit, tot = Counter(), Counter()
        for a, s in zip(df.a.values, students):
            for k in sf[a]:
                tot[k] += 1
                if k in sf[s]:
                    hit[k] += 1
        return hit, tot

    hit, tot = rates(stu)
    null_hits = defaultdict(list)
    for _ in range(200):
        ss = stu.copy()
        for idx in groups:
            ss[idx] = RNG.permutation(ss[idx])
        h, _ = rates(ss)
        for k in tot:
            null_hits[k].append(h[k])
    rows = []
    for k, n in tot.items():
        if n < 150:
            continue
        exp = float(np.mean(null_hits[k]))
        rows.append({"subfield": names[k], "pairs": int(n), "observed": hit[k] / n, "expected": exp / n,
                     "lift": (hit[k] / n) / (exp / n) if exp else None})
    rows.sort(key=lambda r: -r["pairs"])
    res["A3"] = {"pairs": int(len(df)), "subfields": rows}

    top = rows[:15][::-1]
    fig, ax = plt.subplots(figsize=(6.8, 5.6))
    ys = np.arange(len(top))
    for i, r in enumerate(top):
        ax.plot([r["expected"], r["observed"]], [i, i], color=RULE, lw=3, solid_capstyle="round", zorder=1)
    ax.scatter([r["expected"] for r in top], ys, s=34, facecolor="white", edgecolor=INK3, lw=1.3, zorder=2, label="Expected by chance (same cohort)")
    ax.scatter([r["observed"] for r in top], ys, s=40, color=INK, zorder=3, label="Observed")
    ax.set_yticks(ys, [f"{r['subfield']}  ({r['pairs']:,})" for r in top])
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1))
    ax.set_xlabel("Share of an advisor's students who share the advisor's subfield")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=9)
    ax.grid(axis="y", visible=False)
    ax.set_title("Students share their advisor's subfield far more than chance", pad=26)
    fig.text(0, -0.04, "15 subfields with the most advisor–student pairs (count in brackets). Expected: students shuffled within PhD decade, 200 runs.\n"
             "Caveat: many subfield codes come from ProQuest imports that may tag whole subtrees alike.", color=INK3, fontsize=8.5)
    fig.savefig(FIGS / "a3_subfields.png"); plt.close(fig)


# ------------------------------------------------------------------ A4 coverage of dated PhDs
def a4(res, ctx, people, all_edges):
    """Can we track schools over time? Check how dated PhDs connect to the classic lineages."""
    kids = defaultdict(list)
    for a, s in all_edges:  # school membership follows every advisor link, as in the explorer
        kids[a].append(s)
    member = set()
    for sch in ctx["schools"]:
        seen, st = set(sch["founders"]), list(sch["founders"])
        while st:
            for c in kids.get(st.pop(), []):
                if c not in seen:
                    seen.add(c); st.append(c)
        member |= seen
    soc = {p: v["phd"] for p, v in people.items() if not v["f"] & F_OUTSIDE and v["phd"]}
    years = list(range(1950, 2016))
    n = Counter(y for y in soc.values() if 1950 <= y <= 2015)
    linked = Counter(y for p, y in soc.items() if 1950 <= y <= 2015 and p in member)
    pre2000 = sum(v for k, v in n.items() if k < 2000)
    res["A4"] = {"dated_by_year": {y: n[y] for y in years}, "linked_by_year": {y: linked[y] for y in years},
                 "dated_before_2000": pre2000, "dated_2000_2014": sum(n[y] for y in range(2000, 2015)),
                 "share_linked_2000_2014": sum(linked[y] for y in range(2000, 2015)) / max(1, sum(n[y] for y in range(2000, 2015)))}

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.bar(years, [n[y] for y in years], width=0.8, color=RULE, edgecolor="none", label="Dated sociology PhDs")
    ax.bar(years, [linked[y] for y in years], width=0.8, color=INK, edgecolor="none", label="…of whom descend from a curated school")
    ax.set_xlim(1949, 2016)
    ax.set_ylabel("PhDs per year")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.grid(axis="x", visible=False)
    ax.set_title("PhD years exist almost only for 2000–14, and few of those link to classic lineages")
    fig.text(0, -0.08, f"{pre2000:,} dated sociology PhDs before 2000 vs {res['A4']['dated_2000_2014']:,} in 2000–14; "
             f"{res['A4']['share_linked_2000_2014']:.0%} of the latter descend from one of the 12 curated schools.\n"
             "Years from the AFT-MAG mentorship file (Ke et al. 2022). Tracking schools over time needs dated pre-2000 records (ProQuest).",
             color=INK3, fontsize=8.5)
    fig.savefig(FIGS / "a4_coverage.png"); plt.close(fig)
    old = FIGS / "a4_schools.png"
    if old.exists():
        old.unlink()


def main():
    lin, ctx, people, phd_edges, all_edges = load()
    res = {"data": {"people": len(people), "phd_links": len(phd_edges), "sources": lin["meta"].get("outside_sources", {})}}
    a1(res); a2(res, people, phd_edges); a3(res, ctx, people, phd_edges); a4(res, ctx, people, all_edges)
    (OUT / "results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v for k, v in res["A1"].items() if k != "top10"}, indent=1))
    print({k: res["A2"][k] for k in ("pairs", "spearman_rho", "null_overall_rho_mean", "within_decade_rho", "within_perm_p")}, res["A2"]["rho_by_decade"])
    print([(b["bin"], b["n"], round(b["mean"], 2)) for b in res["A2"]["bins"]])
    print([(r["subfield"], r["pairs"], round(r["observed"], 2), round(r["expected"], 3)) for r in res["A3"]["subfields"][:8]])


if __name__ == "__main__":
    main()
