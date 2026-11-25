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
Usage: python -I scripts/export_network.py
"""

import json
import random
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "explorer" / "data"
K_SAMPLE = 500


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

    deg = dict(U.degree())
    nodes = [[n, comp[n], deg[n], round(pr[n] * 1e6, 2), round(bt[n] * 1e6, 1) if n in bt else None,
              round(abs(ev[n]) * 1e4, 2) if n in ev else None, core[n]] for n in G.nodes]

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
