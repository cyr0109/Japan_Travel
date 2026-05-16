"""
Pre-label NER entities for manual review.
Outputs review_spots.csv with auto-guessed add_to_whitelist (1/0).
After human review, run: python import_whitelist.py
"""

import sqlite3
import csv
import re

DB_PATH = "japan_travel.db"
OUTPUT_CSV = "review_spots.csv"
MIN_POSTS = 3  # ignore entities appearing in fewer posts

# ── Auto-reject rules ────────────────────────────────────────────────────────
REJECT_EXACT = {
    "歐洲", "亞洲", "東南亞", "美洲", "非洲", "中東",
    "日本海", "太平洋", "東海", "瀨戶內海", "東京灣", "大阪灣",
    "東北", "關東", "關西", "九州", "四國", "中部", "中國地方",
    "本州", "北陸", "東海地方",
    "東橫", "東橫inn", "東橫Inn",
    "迪士尼",          # theme park, not a spot in this research scope
    "溫泉街",          # generic category
    "東京市區", "大阪市區",
}

REJECT_SUFFIX = ("縣", "都", "道", "府", "市", "區", "町", "村", "郡")
REJECT_CONTAINS = ("飯店", "ホテル", "酒店", "旅館", "hostel",
                   "機場", "空港", "車站", "駅", "地鐵", "捷運",
                   "便利商店", "超市", "百貨", "商場", "購物",
                   "餐廳", "食堂", "レストラン",
                   "機場", "高速公路", "國道")

# ── Auto-accept hints ────────────────────────────────────────────────────────
ACCEPT_CONTAINS = ("山", "湖", "島", "岳", "峽", "瀑布", "神社", "寺",
                   "城", "公園", "溫泉", "海灘", "岬", "半島", "高原",
                   "火山", "滝", "浜", "橋", "閣", "宮", "祠", "堂")


def auto_label(entity: str) -> int:
    if entity in REJECT_EXACT:
        return 0
    if entity.endswith(REJECT_SUFFIX):
        return 0
    if any(kw in entity for kw in REJECT_CONTAINS):
        return 0
    if any(kw in entity for kw in ACCEPT_CONTAINS):
        return 1
    return 1  # default accept; human corrects edge cases


def main():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT entity, COUNT(DISTINCT post_id) as posts, COUNT(*) as mentions
        FROM ner_locations
        GROUP BY entity
        HAVING posts >= ?
        ORDER BY posts DESC
    """, (MIN_POSTS,)).fetchall()
    conn.close()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["entity", "posts", "mentions", "add_to_whitelist", "note"])
        for entity, posts, mentions in rows:
            label = auto_label(entity)
            writer.writerow([entity, posts, mentions, label, ""])

    total = len(rows)
    auto_accept = sum(1 for e, p, m in rows if auto_label(e) == 1)
    auto_reject = total - auto_accept
    print(f"Exported {total} entities to {OUTPUT_CSV}")
    print(f"  Auto-accept: {auto_accept}  Auto-reject: {auto_reject}")
    print(f"  → Open {OUTPUT_CSV}, fix wrong labels, then run: python import_whitelist.py")


if __name__ == "__main__":
    main()
