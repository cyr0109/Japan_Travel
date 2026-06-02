"""
階段十：共現網絡靜態視覺化
輸出：network.png（300 dpi，適合報告使用）
"""

import sqlite3
import math
import colorsys
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "PingFang HK"
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
from collections import Counter

DB_PATH    = "japan_travel.db"
OUTPUT_PNG = "network.png"
MIN_CLUSTER_SIZE = 4

TRULY_HIDDEN = {
    "大雪山連峰", "彌彥山", "葫蘆島", "南阿爾卑斯山脈", "平戶島",
    "菖蒲池", "五十鈴川", "薩摩半島", "觀音街", "宇曾利湖", "伊予灘",
}


def load_data(conn):
    nodes = conn.execute("""
        SELECT sc.spot, sc.cluster_id, sc.degree
        FROM spot_clusters sc
    """).fetchall()
    edges = conn.execute("""
        SELECT spot_a, spot_b, pmi FROM cooccurrence_edges
    """).fetchall()
    return nodes, edges


def cluster_color(cluster_id, alpha=1.0):
    hue = (cluster_id * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.70, 0.88)
    return (r, g, b, alpha)


def community_layout(cluster_map, edges_set, valid_spots):
    """群集中心放在大圓上，內部用 spring layout 排列。"""
    sorted_clusters = sorted(cluster_map.items(), key=lambda x: -len(x[1]))
    n_cls = len(sorted_clusters)
    OUTER_R = 6.0

    pos = {}
    for i, (cid, members) in enumerate(sorted_clusters):
        angle = 2 * math.pi * i / n_cls - math.pi / 2
        cx, cy = OUTER_R * math.cos(angle), OUTER_R * math.sin(angle)

        # 子圖 spring layout
        sub = nx.Graph()
        sub.add_nodes_from(members)
        for a, b in edges_set:
            if a in set(members) and b in set(members):
                sub.add_edge(a, b)

        r = 0.8 + 0.06 * len(members)
        sub_pos = nx.spring_layout(sub, seed=42, k=1.2, scale=r)
        for spot, (x, y) in sub_pos.items():
            pos[spot] = (cx + x, cy + y)

    return pos


def main():
    conn = sqlite3.connect(DB_PATH)
    nodes, edges = load_data(conn)
    conn.close()

    cluster_counts = Counter(row[1] for row in nodes)
    valid_clusters  = {cid for cid, cnt in cluster_counts.items() if cnt >= MIN_CLUSTER_SIZE}
    valid_spots     = {row[0] for row in nodes if row[1] in valid_clusters or row[0] in TRULY_HIDDEN}

    # 建 networkx 圖
    G = nx.Graph()
    G.add_nodes_from(valid_spots)
    edges_set = set()
    for spot_a, spot_b, pmi in edges:
        if spot_a in valid_spots and spot_b in valid_spots:
            G.add_edge(spot_a, spot_b, pmi=pmi)
            edges_set.add((spot_a, spot_b))

    # 群集對應
    spot_cluster = {row[0]: row[1] for row in nodes if row[0] in valid_spots}
    spot_degree  = {row[0]: row[2] for row in nodes if row[0] in valid_spots}
    cluster_map  = {}
    for spot, cid in spot_cluster.items():
        cluster_map.setdefault(cid, []).append(spot)

    # 座標
    pos = community_layout(cluster_map, edges_set, valid_spots)

    # 節點大小 & 顏色
    d_vals = list(spot_degree.values())
    d_min, d_max = min(d_vals), max(d_vals)
    node_sizes  = [200 + ((spot_degree.get(s, d_min) - d_min) / max(d_max - d_min, 1e-9)) * 800
                   for s in G.nodes()]
    node_colors = [cluster_color(spot_cluster.get(s, 0)) for s in G.nodes()]

    # 邊寬
    pmi_vals = [d["pmi"] for _, _, d in G.edges(data=True)]
    p_min, p_max = min(pmi_vals), max(pmi_vals)
    edge_widths = [0.3 + ((d["pmi"] - p_min) / max(p_max - p_min, 1e-9)) * 2.0
                   for _, _, d in G.edges(data=True)]

    # 畫圖
    fig, ax = plt.subplots(figsize=(18, 16), facecolor="#0f0f1a")
    ax.set_facecolor("#0f0f1a")

    # 畫邊
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        width=edge_widths,
        edge_color="white", alpha=0.12,
        style="solid",
    )

    # 畫一般節點
    normal_nodes  = [s for s in G.nodes() if s not in TRULY_HIDDEN]
    hidden_nodes  = [s for s in G.nodes() if s in TRULY_HIDDEN]

    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        nodelist=normal_nodes,
        node_size=[node_sizes[list(G.nodes()).index(s)] for s in normal_nodes],
        node_color=[node_colors[list(G.nodes()).index(s)] for s in normal_nodes],
        linewidths=0.5, edgecolors="white",
    )

    # 畫隱藏景點（金色邊框、較大）
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        nodelist=hidden_nodes,
        node_size=[node_sizes[list(G.nodes()).index(s)] * 1.6 for s in hidden_nodes],
        node_color=[node_colors[list(G.nodes()).index(s)] for s in hidden_nodes],
        linewidths=2.5, edgecolors="#FFD700",
    )

    # 全部節點都標，隱藏景點用較大字體
    labels = {s: s for s in G.nodes() if s in pos}

    nx.draw_networkx_labels(
        G, pos, labels={s: l for s, l in labels.items() if s not in TRULY_HIDDEN},
        ax=ax, font_size=5.5, font_color="white",
        font_family="PingFang HK",
        bbox=dict(boxstyle="round,pad=0.1", fc="black", alpha=0.35, lw=0),
    )
    nx.draw_networkx_labels(
        G, pos, labels={s: l for s, l in labels.items() if s in TRULY_HIDDEN},
        ax=ax, font_size=7.5, font_color="#FFD700",
        font_family="PingFang HK",
        bbox=dict(boxstyle="round,pad=0.15", fc="black", alpha=0.6, lw=0),
    )

    # 圖例
    legend_items = [
        mpatches.Patch(color="#FFD700", label=f"⭐ 真正隱藏景點（n={len(hidden_nodes)}）"),
        mpatches.Patch(color="white",   label=f"主流景點（n={len(normal_nodes)}）"),
        mpatches.Patch(color="gray",    label="節點大小 ∝ Degree"),
        mpatches.Patch(color="gray",    label="邊粗細 ∝ PMI 共現強度"),
    ]
    ax.legend(
        handles=legend_items, loc="lower left",
        facecolor="#1a1a2e", edgecolor="gray",
        labelcolor="white", fontsize=9,
    )

    ax.set_title(
        "PTT 日本景點 PMI 共現網絡（Louvain 群集著色）",
        color="white", fontsize=15, pad=12,
        fontfamily="Arial Unicode MS",
    )
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=300, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"輸出：{OUTPUT_PNG}")


if __name__ == "__main__":
    main()
