"""
RQ2：Mann-Whitney U 檢定
比較隱藏景點（hidden_score >= 0.45）vs 主流景點在六維體驗上的差異。
"""

import sqlite3
import numpy as np
from scipy.stats import mannwhitneyu

DB_PATH = "japan_travel.db"
HIDDEN_THRESHOLD = 0.45

DIMS = {
    "dim_crowd":    "人潮壓力",
    "dim_access":   "交通便利",
    "dim_seasonal": "季節限制",
    "dim_photo":    "打卡價值",
    "dim_value":    "CP 值",
    "dim_planning": "規劃難度",
}


def load_data(conn: sqlite3.Connection) -> tuple[dict, dict]:
    cur = conn.cursor()
    cols = ", ".join(DIMS.keys())
    cur.execute(f"""
        SELECT hidden_score, {cols}
        FROM spot_sentiment
        WHERE hidden_score IS NOT NULL
    """)
    rows = cur.fetchall()

    hidden = {dim: [] for dim in DIMS}
    mainstream = {dim: [] for dim in DIMS}

    for row in rows:
        hs = row[0]
        group = hidden if hs >= HIDDEN_THRESHOLD else mainstream
        for i, dim in enumerate(DIMS.keys()):
            group[dim].append(row[i + 1])

    return hidden, mainstream


def main():
    conn = sqlite3.connect(DB_PATH)
    hidden, mainstream = load_data(conn)
    conn.close()

    n_h = len(hidden["dim_crowd"])
    n_m = len(mainstream["dim_crowd"])
    print(f"隱藏景點：{n_h} 個　主流景點：{n_m} 個\n")

    print(f"{'維度':<10} {'隱藏(mean)':>10} {'主流(mean)':>10} {'U statistic':>13} {'p-value':>10} {'顯著':>6}")
    print("-" * 65)

    for dim, label in DIMS.items():
        h_vals = np.array(hidden[dim])
        m_vals = np.array(mainstream[dim])

        u_stat, p_val = mannwhitneyu(h_vals, m_vals, alternative="two-sided")

        sig = "✅" if p_val < 0.05 else "—"
        print(
            f"{label:<10} {h_vals.mean():>+10.4f} {m_vals.mean():>+10.4f} "
            f"{u_stat:>13.1f} {p_val:>10.4f} {sig:>6}"
        )

    print("\n* p < 0.05 表示兩組在該維度有統計顯著差異（雙尾檢定）")


if __name__ == "__main__":
    main()
