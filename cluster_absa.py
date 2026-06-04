"""
各旅遊圈面向情感分析（Cluster-level ABSA）
輸出：cluster_absa.png
"""

import sqlite3
import numpy as np
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "PingFang HK"
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

DB_PATH    = "japan_travel.db"
OUTPUT_PNG = "cluster_absa.png"

CLUSTER_LABELS = {
    6:  "富士山圈",
    7:  "京阪圈",
    4:  "九州自然圈",
    17: "中部日本圈",
    2:  "北海道道南圈",
    5:  "東京周邊圈",
    1:  "宮島・神戶圈",
    3:  "東北自然圈",
    25: "瀨戶內海島圈",
    21: "關東山區溫泉圈",
    13: "山陰圈",
    0:  "伊勢・熊野圈",
}

DIM_LABELS = {
    "dim_crowd":    "人潮壓力\n(正=人少)",
    "dim_access":   "交通便利",
    "dim_seasonal": "季節限制\n(正=少限制)",
    "dim_photo":    "打卡美景",
    "dim_value":    "CP 值",
    "dim_planning": "規劃難度\n(正=容易)",
}


def load_data(conn):
    rows = conn.execute("""
        SELECT sc.cluster_id, COUNT(*) as n,
               AVG(ss.dim_crowd)    as crowd,
               AVG(ss.dim_access)   as access,
               AVG(ss.dim_seasonal) as seasonal,
               AVG(ss.dim_photo)    as photo,
               AVG(ss.dim_value)    as value,
               AVG(ss.dim_planning) as planning
        FROM spot_sentiment ss
        JOIN spot_clusters sc ON ss.spot = sc.spot
        WHERE sc.cluster_id IN ({})
        GROUP BY sc.cluster_id
    """.format(",".join(str(k) for k in CLUSTER_LABELS))).fetchall()
    return rows


def main():
    conn = sqlite3.connect(DB_PATH)
    rows = load_data(conn)
    conn.close()

    dim_keys = list(DIM_LABELS.keys())
    cluster_order = [6, 7, 4, 17, 2, 5, 1, 3, 25, 21, 13, 0]

    row_map = {r[0]: r for r in rows}
    matrix = []
    y_labels = []

    for cid in cluster_order:
        if cid not in row_map:
            continue
        r = row_map[cid]
        n = r[1]
        vals = [r[2], r[3], r[4], r[5], r[6], r[7]]
        # seasonal: 負值代表限制高 → 反轉讓正 = 好
        vals[2] = -vals[2]
        # crowd: 原本負=人多 → 反轉讓正 = 人少（舒適）
        vals[0] = -vals[0]
        # planning: 負值代表難規劃 → 反轉
        vals[5] = -vals[5]
        matrix.append(vals)
        y_labels.append(f"{CLUSTER_LABELS[cid]}  (n={n})")

    matrix = np.array(matrix)

    # 對每個維度做 z-score 正規化，讓顏色相對比較
    for j in range(matrix.shape[1]):
        col = matrix[:, j]
        std = col.std()
        if std > 1e-9:
            matrix[:, j] = (col - col.mean()) / std

    fig, ax = plt.subplots(figsize=(11, 7), facecolor="#0f0f1a")
    ax.set_facecolor("#0f0f1a")

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rg", ["#c0392b", "#f5f5f5", "#27ae60"]
    )
    im = ax.imshow(matrix, aspect="auto", cmap=cmap, vmin=-2, vmax=2)

    # 格線
    ax.set_xticks(np.arange(len(dim_keys)) - 0.5, minor=True)
    ax.set_yticks(np.arange(len(y_labels)) - 0.5, minor=True)
    ax.grid(which="minor", color="#333", linewidth=0.5)
    ax.tick_params(which="minor", bottom=False, left=False)

    ax.set_xticks(range(len(dim_keys)))
    ax.set_xticklabels(
        [DIM_LABELS[k] for k in dim_keys],
        color="white", fontsize=10,
    )
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, color="white", fontsize=10.5)
    ax.xaxis.tick_top()

    # 數值標注
    raw_rows = load_data(sqlite3.connect(DB_PATH))
    raw_map = {r[0]: r for r in raw_rows}
    for i, cid in enumerate([c for c in cluster_order if c in row_map]):
        r = raw_map[cid]
        raw_vals = [r[2], r[3], r[4], r[5], r[6], r[7]]
        for j, v in enumerate(raw_vals):
            ax.text(j, i, f"{v:+.3f}", ha="center", va="center",
                    fontsize=7.5, color="black" if abs(matrix[i, j]) < 1.2 else "white")

    cbar = plt.colorbar(im, ax=ax, fraction=0.02, pad=0.02)
    cbar.ax.set_ylabel("相對強度（z-score）", color="white", fontsize=9)
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white")

    ax.set_title(
        "PTT 日本各旅遊圈面向情感側寫（綠=正向／紅=負向，數值為原始分數）",
        color="white", fontsize=12, pad=18,
    )

    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"輸出：{OUTPUT_PNG}")

    # 印出文字摘要
    print("\n各旅遊圈面向摘要（原始分數）")
    print(f"{'旅遊圈':<16} {'人潮':>6} {'交通':>6} {'季節':>6} {'打卡':>6} {'CP值':>6} {'規劃':>6}")
    print("-" * 58)
    for cid in cluster_order:
        if cid not in raw_map:
            continue
        r = raw_map[cid]
        print(f"{CLUSTER_LABELS[cid]:<16} "
              f"{r[2]:>+6.3f} {r[3]:>+6.3f} {r[4]:>+6.3f} "
              f"{r[5]:>+6.3f} {r[6]:>+6.3f} {r[7]:>+6.3f}")


if __name__ == "__main__":
    main()
