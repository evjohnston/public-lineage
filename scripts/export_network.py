"""Field-level network measures for the explorer's 3D sociogram.

Reads explorer/data/lineage.json (advisor links after merges) and writes explorer/data/network.json:
  meta: whole-network statistics (size, components, degree, assortativity, diameter estimate)
  nodes: [pid, component_rank, degree, pagerank, betweenness, eigenvector, core]
    component_rank  0 = largest connected component (links treated as undirected)
    degree          advisors + students
    pagerank        on links reversed (student -> advisor), so credit flows up to advisors whose
                    lines are large: "influence through descendants". Scaled x 1e6.
    betweenness     share of shortest paths through the person, largest component only, estimated
                    from 500 sampled sources (seeded). Scaled x 1e6; null outside the largest component.
    eigenvector     largest component only; connected to well-connected people. Scaled x 1e4.
    core            k-core number: the deepest shell of mutually connected people they belong to.
    x, y, z         3D position (DrL force-directed layout, igraph), scaled to roughly +-1000.
The layout of all ~45k people takes about 10 minutes, so positions are cached in
data/external/network_layout.json and reused; people new since the cache are placed beside their
neighbours. --relayout recomputes everything.
Usage: python -I scripts/export_network.py [--relayout]
"""

import json
import random
import sys
import time
from pathlib import Path

import networkx as nx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "explorer" / "data"
K_SAMPLE = 500
LAYOUT = ROOT / "data" / "external" / "network_layout.json"
SCALE = 60.0


def layout(G, U):
    """3D positions for every node: cached DrL layout, with new nodes placed next to neighbours."""
    cache = {} if "--relayout" in sys.argv or not LAYOUT.exists() else {int(k): v for k, v in json.loads(LAYOUT.read_text()).items()}
    nodes = list(G.nodes)
    if not cache:
        import igraph as ig
        ix = {n: i for i, n in enumerate(nodes)}
        g = ig.Graph(n=len(nodes), edges=[(ix[a], ix[b]) for a, b in U.edges])
        print(f"3D layout of {len(nodes):,} people (about 10 minutes)", flush=True)
        t = time.time()
        xyz = np.array(g.layout_drl(dim=3).coords) * SCALE
        print(f"  done in {time.time() - t:.0f}s", flush=True)
        cache = {n: [round(float(v), 1) for v in xyz[i]] for i, n in enumerate(nodes)}
    else:
        rng = np.random.default_rng(7)
        missing = [n for n in nodes if n not in cache]
        new = len(missing)
        for _ in range(3):  # a few passes, so chains of new people settle near placed ones
            for n in list(missing):
                near = [cache[m] for m in U.neighbors(n) if m in cache]
                if near:
                    cache[n] = [round(float(v), 1) for v in np.mean(near, axis=0) + rng.normal(0, 12, 3)]
                    missing.remove(n)
        for n in missing:  # unconnected newcomers: a random point in the outer shell
            v = rng.normal(0, 1, 3); v = v / np.linalg.norm(v) * rng.uniform(900, 1050)
            cache[n] = [round(float(x), 1) for x in v]
        print(f"layout: reused cached positions; placed {new:,} new people ({len(missing):,} with no placed neighbour)", flush=True)
    LAYOUT.write_text(json.dumps({str(n): cache[n] for n in nodes}, separators=(",", ":")))
    return cache


def diameter_estimate(U, start, sweeps=4):
    """Lower bound by repeated double sweeps (exact diameter is too slow for ~17k nodes)."""
    best, node = 0, start
    for _ in range(sweeps):
        d = nx.single_source_shortest_path_length(U, node)
        far, dist = max(d.items(), key=lambda x: x[1])
        if dist <= best:
            break
        best, node = dist, far
    return best


def arrange(cache, comps):
    """Main tree at the centre; every other cluster keeps its own shape but moves out to a shell
    around it (bigger clusters nearer), so the picture separates the connected field from fragments."""
    rng = np.random.default_rng(11)
    main = np.array([cache[n] for n in comps[0]])
    c0 = main.mean(axis=0)
    R = float(np.percentile(np.linalg.norm(main - c0, axis=1), 95))
    out = {n: [round(float(v), 1) for v in np.array(cache[n]) - c0] for n in comps[0]}
    big = max(len(c) for c in comps[1:]) if len(comps) > 1 else 1
    for comp in comps[1:]:
        pts = np.array([cache[n] for n in comp])
        local = pts - pts.mean(axis=0)
        span = float(np.abs(local).max()) or 1.0
        local = local * min(1.0, (8 + 6 * np.log1p(len(comp))) / span)  # keep fragments compact
        d = rng.normal(0, 1, 3); d /= np.linalg.norm(d)
        r = R * (1.25 + 0.55 * (1 - np.log1p(len(comp)) / np.log1p(big)) + rng.uniform(0, 0.12))
        for n, v in zip(comp, local + d * r):
            out[n] = [round(float(x), 1) for x in v]
    return out


def main():
    lin = json.loads((DATA / "lineage.json").read_text())
    G = nx.DiGraph()
    G.add_nodes_from(r[0] for r in lin["people"])
    known = set(G.nodes)  # links to people missing from the export are skipped, as in the explorer
    G.add_edges_from((m, t) for m, t, *_ in lin["edges"] if m != t and m in known and t in known)
    U = G.to_undirected()
    comps = sorted(nx.connected_components(U), key=len, reverse=True)
    comp = {n: i for i, c in enumerate(comps) for n in c}
    big = U.subgraph(comps[0]).copy()

    print("pagerank", flush=True)
    pr = nx.pagerank(G.reverse(copy=False), alpha=0.85)
    print(f"betweenness ({K_SAMPLE} sampled sources)", flush=True)
    bt = nx.betweenness_centrality(big, k=min(K_SAMPLE, len(big)), seed=7)
    print("eigenvector", flush=True)
    ev = nx.eigenvector_centrality_numpy(big)
    core = nx.core_number(U)

    pos = arrange(layout(G, U), comps)
    deg = dict(U.degree())
    nodes = [[n, comp[n], deg[n], round(pr[n] * 1e6, 2), round(bt[n] * 1e6, 1) if n in bt else None,
              round(abs(ev[n]) * 1e4, 2) if n in ev else None, core[n], *pos[n]] for n in G.nodes]

    random.seed(7)
    sample = random.sample(list(big.nodes), 60)
    lengths = [d for s in sample for d in nx.single_source_shortest_path_length(big, s).values() if d]
    degs = [d for _, d in U.degree()]
    meta = {
        "people": G.number_of_nodes(), "links": G.number_of_edges(), "components": len(comps),
        "largest": len(comps[0]), "largest_share": len(comps[0]) / G.number_of_nodes(),
        "components_10_plus": sum(1 for c in comps if len(c) >= 10),
        "isolates": sum(1 for c in comps if len(c) == 1),
        "mean_degree": sum(degs) / len(degs), "max_degree": max(degs),
        "assortativity": nx.degree_assortativity_coefficient(U),
        "diameter_lower_bound": diameter_estimate(big, max(big.degree, key=lambda x: x[1])[0]),
        "mean_distance_sampled": sum(lengths) / len(lengths),
        "max_core": max(core.values()),
        "measures": {"degree": "advisors + students", "pagerank": "influence through descendants (PageRank on student→advisor links)",
                     "betweenness": f"brokerage between lineages (largest component, {K_SAMPLE} sampled sources)",
                     "eigenvector": "ties to well-tied people (largest component)", "core": "k-core shell"},
    }
    (DATA / "network.json").write_text(json.dumps({"meta": meta, "nodes": nodes}, separators=(",", ":"), allow_nan=False))
    print(json.dumps({k: v for k, v in meta.items() if k != "measures"}, indent=1))


if __name__ == "__main__":
    main()
