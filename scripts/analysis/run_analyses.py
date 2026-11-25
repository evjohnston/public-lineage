"""First-pass analyses of the sociology lineage network.

Reads the cleaned, merged exports (explorer/data/lineage.json, context.json) and the faculty hiring
census, writes figures to docs/analysis/figs/ and numbers to docs/analysis/results.json.

  A1  Placement concentration: how concentrated is US sociology faculty production?
  A2  Fecundity transmission: do advisors with many students produce students with many students?
  A3  Subfield inheritance: do students share their advisor's subfield beyond cohort chance?
  A3b Topic inheritance: the same test on OpenAlex publication topics (no ProQuest circularity)
  A4  Schools over time: what share of each decade's documented PhDs descend from each curated school?
      A4b repeats it within each source of years, to separate history from source mix.
  A5  Advisor standing and placement: within the same PhD program and decade, do students of more
      prolific or more cited advisors get faculty jobs at higher-ranked sociology departments?

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
    people = {r[0]: {"name": r[1], "f": r[3], "ns": r[4], "nd": r[5], "h": r[9] if len(r) > 9 else None, "phd": r[12] if len(r) > 12 else None,
                     "year": r[13] if len(r) > 13 else None, "basis": r[14] if len(r) > 14 else None}
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


# ------------------------------------------------------------------ A3b topic inheritance
def a3b(res, ctx, people, phd_edges):
    """Do students publish on their advisor's OpenAlex topics? Topics come from each person's own
    papers, so unlike the ProQuest subfield codes in A3 they can't be copied down a subtree."""
    tp = {int(k): set(v[5]) for k, v in ctx["person"].items() if v[5]}
    names = [t["name"] for t in ctx["topics"]]
    dec = lambda p: (people[p]["year"] or 0) // 10 * 10
    pairs = [(a, s, dec(s)) for a, s in phd_edges if a in tp and s in tp and a != s]
    df = pd.DataFrame(pairs, columns=["a", "s", "decade"])
    adv, stu = df.a.values, df.s.values
    groups = [g.index.values for _, g in df.groupby("decade") if len(g) > 1]

    def stats_(students):
        any_hit, hit, tot = 0, Counter(), Counter()
        for a, s in zip(adv, students):
            shared = tp[a] & tp[s]
            any_hit += bool(shared)
            for k in tp[a]:
                tot[k] += 1
                hit[k] += k in shared
        return any_hit, hit, tot

    obs_any, hit, tot = stats_(stu)
    null_any, null_hits = [], defaultdict(list)
    for _ in range(200):
        ss = stu.copy()
        for idx in groups:
            ss[idx] = RNG.permutation(ss[idx])
        na, h, _ = stats_(ss)
        null_any.append(na)
        for k in tot:
            null_hits[k].append(h[k])
    n = len(df)
    p = float((np.sum(np.array(null_any) >= obs_any) + 1) / (len(null_any) + 1))
    # joint papers make topics match mechanically: repeat for pairs who never co-authored
    co = json.loads((ROOT / "explorer" / "data" / "coauthors.json").read_text())
    coset = {frozenset(e[:2]) for e in co["edges"]}
    solo = np.array([frozenset((a, s)) not in coset for a, s in zip(adv, stu)])
    solo_any = sum(bool(tp[a] & tp[s]) for a, s, k in zip(adv, stu, solo) if k)
    rows = []
    for k, m in tot.items():
        if m < 60:
            continue
        exp = float(np.mean(null_hits[k]))
        rows.append({"topic": names[k], "pairs": int(m), "observed": hit[k] / m, "expected": exp / m,
                     "lift": (hit[k] / m) / (exp / m) if exp else None})
    rows.sort(key=lambda r: -r["pairs"])
    res["A3b"] = {"pairs": n, "share_any_topic": obs_any / n, "expected_any_topic": float(np.mean(null_any)) / n,
                  "perm_p": p, "topics": rows,
                  "non_coauthor_pairs": int(solo.sum()), "non_coauthor_share_any_topic": solo_any / max(1, solo.sum())}

    top = rows[:15][::-1]
    fig, ax = plt.subplots(figsize=(6.8, 5.6))
    ys = np.arange(len(top))
    for i, r in enumerate(top):
        ax.plot([r["expected"], r["observed"]], [i, i], color=RULE, lw=3, solid_capstyle="round", zorder=1)
    ax.scatter([r["expected"] for r in top], ys, s=34, facecolor="white", edgecolor=INK3, lw=1.3, zorder=2, label="Expected by chance (same cohort)")
    ax.scatter([r["observed"] for r in top], ys, s=40, color=INK, zorder=3, label="Observed")
    ax.set_yticks(ys, [f"{r['topic']}  ({r['pairs']:,})" for r in top])
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1))
    ax.set_xlabel("Share of an advisor's students who publish on the advisor's topic")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=9)
    ax.grid(axis="y", visible=False)
    ax.set_title("Students publish on their advisor's topics far more than chance", pad=26)
    fig.text(0, -0.05, f"Advisor–student pairs where both are matched to OpenAlex (n = {n:,}); topics = each person's 3 most frequent OpenAlex topics.\n"
             f"{obs_any / n:.0%} of pairs share at least one topic vs {np.mean(null_any) / n:.0%} expected (students shuffled within PhD decade, 200 runs); "
             f"{solo_any / max(1, solo.sum()):.0%} among the {solo.sum():,} pairs who never co-authored.",
             color=INK3, fontsize=8.5)
    fig.savefig(FIGS / "a3b_topics.png"); plt.close(fig)


# ------------------------------------------------------------------ A4 schools over time
DOCUMENTED = {1: "Recorded training years", 2: "Dissertation, grant or ORCID record", 3: "Wikidata birth year + 28"}


def a4(res, ctx, people, all_edges):
    """Share of each decade's sociology PhDs that descend from each curated school.
    Only documented years count (basis 1-3). Years estimated from relatives (basis 5) exist only for
    people with dated relatives, i.e. linked people, so they would inflate the linked share."""
    kids = defaultdict(list)
    for a, s in all_edges:  # school membership follows every advisor link, as in the explorer
        kids[a].append(s)
    members = {}
    for sch in ctx["schools"]:
        seen, st = set(sch["founders"]), list(sch["founders"])
        while st:
            for c in kids.get(st.pop(), []):
                if c not in seen:
                    seen.add(c); st.append(c)
        members[sch["id"]] = seen - set(sch["founders"])
    anyschool = set().union(*members.values())
    soc = {p: (v["year"] // 10 * 10, v["basis"]) for p, v in people.items()
           if not v["f"] & F_OUTSIDE and v["year"] and v["basis"] in DOCUMENTED and 1880 <= v["year"] <= 2019}
    decades = list(range(1880, 2020, 10))
    by_basis = {b: Counter(d for d, bb in soc.values() if bb == b) for b in DOCUMENTED}
    n = Counter(d for d, _ in soc.values())
    MIN_N = 100
    shown = [d for d in decades if n[d] >= MIN_N]
    share = {sid: {d: sum(1 for p in m if p in soc and soc[p][0] == d) / n[d] for d in shown} for sid, m in members.items()}
    share_any = {d: sum(1 for p in anyschool if p in soc and soc[p][0] == d) / n[d] for d in shown}
    res["A4"] = {"documented_by_decade": {d: n[d] for d in decades},
                 "by_basis": {DOCUMENTED[b]: {d: c[d] for d in decades} for b, c in by_basis.items()},
                 "min_n": MIN_N, "decades_shown": shown, "share_any_school": share_any,
                 "share_by_school": {sid: v for sid, v in share.items()},
                 "excluded_estimated": sum(1 for v in people.values() if v["basis"] in (4, 5) and not v["f"] & F_OUTSIDE)}

    # A4b: the same shares within each source of years. If a trend appears inside every source it is
    # not an artifact of the source mix changing by decade.
    MIN_B = 80
    focus = ["any"] + [sid for sid, _ in sorted(((sid, max(v.values() or [0])) for sid, v in share.items()), key=lambda x: -x[1])[:5]]
    by_src = {}
    for b in DOCUMENTED:
        pb = {p: d for p, (d, bb) in soc.items() if bb == b}
        nb = Counter(pb.values())
        ds = [d for d in decades if nb[d] >= MIN_B]
        by_src[b] = {"n": {d: nb[d] for d in ds}}
        for sid in focus:
            m = anyschool if sid == "any" else members[sid]
            by_src[b][sid] = {d: sum(1 for p in m if pb.get(p) == d) / nb[d] for d in ds}
    res["A4"]["by_source"] = {DOCUMENTED[b]: v for b, v in by_src.items()}
    sname = {s_["id"]: s_["name"] for s_ in ctx["schools"]} | {"any": "Any curated school"}
    fig, axes = plt.subplots(2, 3, figsize=(9, 5.4), sharex=True)
    styles = {1: ("-", INK), 2: ("-", INK3), 3: ((0, (3, 2)), "#9a968d")}
    for ax, sid in zip(axes.flat, focus):
        for b in DOCUMENTED:
            v = by_src[b][sid]
            if v:
                ax.plot(list(v), list(v.values()), ls=styles[b][0], color=styles[b][1], lw=2, marker="o", ms=3.5, label=DOCUMENTED[b])
        ax.set_title(sname[sid], fontsize=10, pad=4)
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
        ax.tick_params(labelsize=8.5)
    for ax in axes[-1]:
        ax.set_xticks(decades[4::2], [f"{d}s" for d in decades[4::2]])
    h, l = axes.flat[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower left", bbox_to_anchor=(0.01, 0.0), ncol=3, frameon=False, fontsize=9)
    fig.suptitle("School shares computed separately for each source of PhD years", x=0.01, ha="left", fontweight=700, fontsize=12)
    fig.text(0.01, -0.02, f"Each line uses only PhDs dated by one source; decades with at least {MIN_B} such PhDs. Panels have their own y scale.",
             color=INK3, fontsize=8.5)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(FIGS / "a4b_by_source.png"); plt.close(fig)

    # coverage: documented PhDs per decade, by where the year comes from
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    shades = {1: INK, 2: INK3, 3: "#b9b5ac"}
    styles = {1: "-", 2: "-", 3: (0, (3, 2))}
    for b in DOCUMENTED:  # separate lines, not stacked: stacked segments on a log axis misstate size
        ax.plot(decades, [by_basis[b][d] or np.nan for d in decades], color=shades[b], lw=2, ls=styles[b], marker="o", ms=4, label=DOCUMENTED[b])
    ax.set_yscale("log"); ax.set_ylim(1, max(max(c.values()) for c in by_basis.values()) * 3)
    ax.set_xticks(decades[::2], [f"{d}s" for d in decades[::2]])
    ax.set_ylabel("Sociology PhDs (log scale)")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.grid(axis="x", visible=False)
    ax.set_title("Documented PhD years now reach back a century, thinly")
    pre = sum(n[d] for d in decades if d < 2000)
    fig.text(0, -0.08, f"{pre:,} documented sociology PhDs before 2000, {sum(n[d] for d in decades if d >= 2000):,} from 2000. "
             f"Excludes {res['A4']['excluded_estimated']:,} years estimated from relatives or first papers.", color=INK3, fontsize=8.5)
    fig.savefig(FIGS / "a4_coverage.png"); plt.close(fig)

    # one small panel per school, same y scale, so shares compare across schools
    order = sorted(ctx["schools"], key=lambda s: -max(share[s["id"]].values() or [0]))
    cols = 4
    rows_ = int(np.ceil(len(order) / cols))
    ymax = max(max(v.values() or [0]) for v in share.values()) * 1.15
    fig, axes = plt.subplots(rows_, cols, figsize=(9, 2.0 * rows_ + 0.6), sharex=True, sharey=True)
    for ax, sch in zip(axes.flat, order):
        v = share[sch["id"]]
        ax.plot(shown, [v[d] for d in shown], color=INK, lw=2, marker="o", ms=3.5)
        ax.set_title(sch["name"], fontsize=10, pad=4)
        ax.set_ylim(0, ymax)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
        ax.tick_params(labelsize=8.5)
    for ax in list(axes.flat)[len(order):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xticks(shown[::2], [f"{d}s" for d in shown[::2]])
    fig.suptitle("Share of each decade's documented sociology PhDs descending from each school", x=0.01, ha="left", fontweight=700, fontsize=12)
    fig.text(0.01, -0.03, f"Decades with at least {MIN_N} documented PhDs: {shown[0]}s–{shown[-1]}s. A person can descend from several schools. "
             f"Founders from data/schools.json; descent follows every advisor link.\nAny school: "
             + ", ".join(f"{d}s {share_any[d]:.0%}" for d in shown) + ".", color=INK3, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(FIGS / "a4_schools.png"); plt.close(fig)


# ------------------------------------------------------------------ A5 advisor standing and placement
def census_matcher():
    """ORCID organisation name -> hiring-census institution id. Exact names only (after dropping
    'the', 'at', 'of', 'campus'), plus a flagship-campus suffix; never a partial match, which mapped
    George Washington to WashU and NYU Abu Dhabi to NYU."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from match_hiring_institutions import expand, toks
    inst = pd.read_parquet(ROOT / "data" / "external" / "faculty_hiring_sociology_institutions.parquet")
    mp = pd.read_parquet(ROOT / "data" / "external" / "faculty_hiring_inst_map.parquet")
    mp = mp[mp.hiring_id.isin(inst.institution_id)]
    drop = {"the", "at", "main", "campus", "of"}
    flag = {"columbia", "manoa", "madison", "amherst", "ann", "arbor", "chapel", "hill", "twin", "cities", "urbana",
            "champaign", "bloomington", "austin", "berkeley", "columbus", "new", "brunswick", "seattle", "college", "park", "university"}
    norm = lambda x: tuple(t for t in toks(x) if t not in drop)
    names = {}
    for _, r in inst.iterrows():
        names.setdefault(norm(expand(r.institution_name)), r.institution_id)
    for _, r in mp.dropna(subset=["aft_name"]).iterrows():
        names.setdefault(norm(r.aft_name), r.hiring_id)

    def match(org):
        t = norm(org or "")
        if t in names:
            return names[t]
        for k in range(len(t) - 1, 1, -1):
            if t[:k] in names and set(t[k:]) <= flag:
                return names[t[:k]]
        return None
    n_ranked = int(inst.ordinal_prestige_rank.max()) + 1
    pct = {i: 1 - r / (n_ranked - 1) for i, r in zip(inst.institution_id, inst.ordinal_prestige_rank)}  # 1 = top
    mq = mp.dropna(subset=["locid"])
    loc2h = dict(zip(mq.locid.astype(int), mq.hiring_id))
    return match, pct, loc2h


def a5(res, ctx, people, phd_edges):
    match, pct, loc2h = census_matcher()
    careers = json.loads((ROOT / "explorer" / "data" / "careers.json").read_text())
    FAC = ("professor", "lecturer")

    def first_job(pid, y):
        c = careers.get(str(pid))
        if not c:
            return None
        jobs = sorted((e for e in c[2] if e[0] == "employment" and e[4] and y - 1 <= e[4] <= y + 6 and e[3]
                       and any(f in e[3].lower() for f in FAC) and not any(x in e[3].lower() for x in ("emerit", "visiting"))),
                      key=lambda e: e[4])
        return jobs[0] if jobs else None

    rows = []
    for a, s in phd_edges:
        S, A = people[s], people[a]
        if S["f"] & F_OUTSIDE or not S["year"] or S["basis"] not in DOCUMENTED:
            continue
        prog = loc2h.get(int((ctx["person"].get(str(s)) or [None])[0] or -1))
        if prog is None:
            continue
        j = first_job(s, S["year"])
        ji = match(j[1]) if j else None
        fl = (ctx["person"].get(str(s)) or [None, None])[1]
        fi = loc2h.get(int(fl)) if fl is not None else None
        rows.append({"s": s, "prog": prog, "decade": S["year"] // 10 * 10, "adv_students": A["ns"] - 1,
                     "adv_h": A["h"], "first_job": j is not None, "first_pct": pct.get(ji) if ji is not None else None,
                     "fac_pct": pct.get(fi) if fi is not None else None})
    df = pd.DataFrame(rows).drop_duplicates("s")  # a student with two advisors keeps the first listed
    df["stratum"] = df.prog.astype(str) + "-" + df.decade.astype(str)

    def test(d, x, y):
        d = d.dropna(subset=[x, y])
        d = d[d.groupby("stratum")[y].transform("size") >= 2]
        # advisor measure as rank within the student's own program and decade (0 = lowest, 1 = highest)
        d = d.assign(xr=d.groupby("stratum")[x].rank(pct=True, method="average"))
        d = d[d.groupby("stratum")[x].transform("nunique") >= 2].reset_index(drop=True)
        groups = [g.index.values for _, g in d.groupby("stratum")]
        xv, yv = d.xr.values, d[y].values.astype(float)

        def stat(v):  # pooled within-stratum covariance-free Spearman: correlate deviations from stratum means
            dev = v.copy()
            for idx in groups:
                dev[idx] = v[idx] - v[idx].mean()
            xd = xv.copy()
            for idx in groups:
                xd[idx] = xv[idx] - xv[idx].mean()
            return float(np.corrcoef(xd, dev)[0, 1])
        obs = stat(yv)
        null = []
        for _ in range(1000):
            vv = yv.copy()
            for idx in groups:
                vv[idx] = RNG.permutation(vv[idx])
            null.append(stat(vv))
        p = float((np.sum(np.abs(null) >= abs(obs)) + 1) / (len(null) + 1))
        d = d.assign(rel=yv - d.groupby("stratum")[y].transform("mean").values,
                     tert=pd.cut(d.xr, [0, 1 / 3, 2 / 3, 1.0001], labels=["Bottom third", "Middle third", "Top third"], include_lowest=True))
        bins = []
        for lab, g in d.groupby("tert", observed=True):
            boots = [RNG.choice(g.rel.values, len(g)).mean() for _ in range(1000)]
            bins.append({"bin": lab, "n": int(len(g)), "mean": float(g.rel.mean()),
                         "lo": float(np.percentile(boots, 2.5)), "hi": float(np.percentile(boots, 97.5))})
        return {"n": int(len(d)), "strata": len(groups), "r": obs, "perm_p": p, "bins": bins}

    out = {}
    specs = [("first", "first_pct", "Rank of first faculty job (ORCID)"), ("fac", "fac_pct", "Rank of later faculty institution (lineage data)")]
    for key, y, _ in specs:
        for x in ("adv_students", "adv_h"):
            out[f"{key}:{x}"] = test(df, x, y)
    has_job = df.dropna(subset=["adv_students"])
    out["got_ranked_first_job"] = test(df[df.first_job].assign(ranked=lambda d: d.first_pct.notna().astype(float)), "adv_students", "ranked")
    res["A5"] = {"students": int(len(df)), "with_orcid_faculty_job": int(df.first_job.sum()),
                 "first_job_ranked": int(df.first_pct.notna().sum()), "fac_ranked": int(df.fac_pct.notna().sum()), "tests": out}

    fig, axes = plt.subplots(2, 2, figsize=(8.4, 6.2), sharey="row")
    xl = {"adv_students": "advisor's other PhD students", "adv_h": "advisor's h-index"}
    for i, (key, y, lab) in enumerate(specs):
        for j, x in enumerate(("adv_students", "adv_h")):
            ax, t = axes[i, j], out[f"{key}:{x}"]
            b = t["bins"]
            xs = np.arange(len(b))
            ax.errorbar(xs, [v["mean"] for v in b], yerr=[[v["mean"] - v["lo"] for v in b], [v["hi"] - v["mean"] for v in b]],
                        fmt="o", color=INK, ms=7, lw=1.4, capsize=0)
            ax.axhline(0, color=INK3, lw=1)
            ax.set_xticks(xs, [v["bin"] for v in b], fontsize=9)
            ax.set_xlim(-0.5, len(b) - 0.5)
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v * 100:+.0f}"))
            ax.set_title(f"{lab}\nby {xl[x]}", fontsize=10, pad=4)
            ax.text(0.98, 0.04, f"n = {t['n']:,} · r = {t['r']:.2f} · p = {t['perm_p']:.2f}", transform=ax.transAxes,
                    ha="right", color=INK3, fontsize=8.5)
            ax.grid(axis="x", visible=False)
        axes[i, 0].set_ylabel("Percentile points vs\nclassmates' average")
    fig.suptitle("No clear advisor effect on placement, relative to classmates from the same program and decade", x=0.01, ha="left", fontweight=700, fontsize=12)
    fig.text(0.01, -0.05, "Advisor measure ranked within the student's PhD program and decade. Placement = prestige percentile of the hiring department "
             "(Wapman et al. 2022 ranks; 100 = top).\nOnly students whose placement is a ranked US sociology department. 95% bootstrap CIs; p from 1,000 within-stratum permutations.",
             color=INK3, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(FIGS / "a5_placement.png"); plt.close(fig)


def main():
    lin, ctx, people, phd_edges, all_edges = load()
    res = {"data": {"people": len(people), "phd_links": len(phd_edges), "sources": lin["meta"].get("outside_sources", {})}}
    a1(res); a2(res, people, phd_edges); a3(res, ctx, people, phd_edges); a3b(res, ctx, people, phd_edges); a4(res, ctx, people, all_edges); a5(res, ctx, people, phd_edges)
    (OUT / "results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v for k, v in res["A1"].items() if k != "top10"}, indent=1))
    print({k: res["A2"][k] for k in ("pairs", "spearman_rho", "null_overall_rho_mean", "within_decade_rho", "within_perm_p")}, res["A2"]["rho_by_decade"])
    print([(b["bin"], b["n"], round(b["mean"], 2)) for b in res["A2"]["bins"]])
    print([(r["subfield"], r["pairs"], round(r["observed"], 2), round(r["expected"], 3)) for r in res["A3"]["subfields"][:8]])
    print({k: res["A3b"][k] for k in ("pairs", "share_any_topic", "expected_any_topic", "perm_p")},
          [(r["topic"], r["pairs"], round(r["observed"], 2), round(r["expected"], 3)) for r in res["A3b"]["topics"][:8]])
    print(res["A4"]["documented_by_decade"], {d: round(v, 3) for d, v in res["A4"]["share_any_school"].items()})
    print({k: {d: round(x, 3) for d, x in v.items()} for k, v in res["A4"]["share_by_school"].items()})
    for b, v in res["A4"]["by_source"].items():
        print(b, v["n"]); [print("   ", k, {d: round(x, 3) for d, x in vv.items()}) for k, vv in v.items() if k != "n"]
    print({k: v for k, v in res["A5"].items() if k != "tests"})
    for k, t in res["A5"]["tests"].items():
        print(k, t["n"], t["strata"], round(t["r"], 3), t["perm_p"], [(b["bin"], b["n"], round(b["mean"], 3)) for b in t["bins"]])


if __name__ == "__main__":
    main()
