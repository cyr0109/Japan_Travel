"""
Louvain community detection on PMI co-occurrence network.
Saves cluster assignments to SQLite table: spot_clusters.
Prints modularity Q and cluster summaries.
"""

import sqlite3
import logging
import random
import networkx as nx
import community as community_louvain  # python-louvain

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH   = "japan_travel.db"
SEED      = 42
N_RUNS    = 10   # run Louvain N times, keep best Q


def load_graph(conn: sqlite3.Connection) -> nx.Graph:
    G = nx.Graph()
    rows = conn.execute(
        "SELECT spot_a, spot_b, cooccur, pmi FROM cooccurrence_edges"
    ).fetchall()
    for a, b, cooccur, pmi in rows:
        G.add_edge(a, b, weight=pmi, cooccur=cooccur)

    # add isolated whitelisted spots as nodes (no edges)
    for (spot,) in conn.execute("SELECT name_zh FROM spot_whitelist"):
        if spot not in G:
            G.add_node(spot)

    log.info("Graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


def best_louvain(G: nx.Graph, n_runs: int, seed: int) -> tuple[dict, float]:
    best_partition, best_q = None, -1.0
    for i in range(n_runs):
        random.seed(seed + i)
        partition = community_louvain.best_partition(G, weight="weight", random_state=seed + i)
        q = community_louvain.modularity(partition, G, weight="weight")
        if q > best_q:
            best_q = q
            best_partition = partition
    return best_partition, best_q


def save_clusters(conn: sqlite3.Connection, partition: dict, G: nx.Graph) -> None:
    conn.execute("DROP TABLE IF EXISTS spot_clusters")
    conn.execute("""
        CREATE TABLE spot_clusters (
            spot        TEXT PRIMARY KEY,
            cluster_id  INTEGER NOT NULL,
            degree      REAL,
            betweenness REAL,
            clustering  REAL
        )
    """)
    conn.execute("CREATE INDEX idx_cluster ON spot_clusters(cluster_id)")

    # compute network metrics (only on connected subgraph)
    connected = G.subgraph([n for n in G if G.degree(n) > 0])
    degree_cent   = nx.degree_centrality(connected)
    between_cent  = nx.betweenness_centrality(connected, weight="weight", normalized=True)
    clust_coeff   = nx.clustering(connected, weight="weight")

    rows = []
    for node, cluster_id in partition.items():
        rows.append((
            node,
            cluster_id,
            round(degree_cent.get(node, 0), 4),
            round(between_cent.get(node, 0), 4),
            round(clust_coeff.get(node, 0), 4),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO spot_clusters VALUES (?,?,?,?,?)", rows
    )
    conn.commit()


def print_summary(conn: sqlite3.Connection, best_q: float) -> None:
    log.info("Best Modularity Q = %.4f", best_q)

    clusters = conn.execute("""
        SELECT cluster_id, COUNT(*) as size
        FROM spot_clusters
        GROUP BY cluster_id
        ORDER BY size DESC
    """).fetchall()

    log.info("Total clusters: %d", len(clusters))
    print(f"\n{'='*60}")
    print(f"Modularity Q = {best_q:.4f}  ({'significant' if best_q >= 0.3 else 'weak'})")
    print(f"{'='*60}")

    for cluster_id, size in clusters:
        if size < 3:
            continue
        # top 5 nodes by degree centrality
        top_nodes = conn.execute("""
            SELECT spot, degree, betweenness
            FROM spot_clusters
            WHERE cluster_id = ?
            ORDER BY degree DESC
            LIMIT 5
        """, (cluster_id,)).fetchall()

        top_names = [r[0] for r in top_nodes]
        print(f"\nCluster {cluster_id:>2}  ({size} spots)")
        print(f"  核心景點: {' / '.join(top_names)}")

        # doc frequency from spot_stats
        freq_rows = conn.execute("""
            SELECT s.spot, st.doc_freq
            FROM spot_clusters s
            JOIN spot_stats st ON s.spot = st.spot
            WHERE s.cluster_id = ?
            ORDER BY st.doc_freq DESC
            LIMIT 8
        """, (cluster_id,)).fetchall()
        freq_str = ", ".join(f"{r[0]}({r[1]})" for r in freq_rows)
        print(f"  高頻景點: {freq_str}")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    G = load_graph(conn)

    log.info("Running Louvain x%d (seed=%d)…", N_RUNS, SEED)
    partition, best_q = best_louvain(G, N_RUNS, SEED)

    save_clusters(conn, partition, G)
    print_summary(conn, best_q)
    conn.close()
