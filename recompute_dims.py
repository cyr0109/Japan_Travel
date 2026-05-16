"""
Recompute six-dimension scores using ±150 char context windows.
Keeps existing sentiment scores unchanged; only updates dim_* columns.
"""

import sqlite3
import logging
import re
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH     = "japan_travel.db"
CONTEXT_WIN = 150   # chars on each side of entity mention

DIM_KEYWORDS = {
    "crowd": {
        "neg": ["排隊", "人山人海", "人擠人", "等很久", "大排長龍", "人超多", "很擠", "塞車", "塞滿", "人潮洶湧"],
        "pos": ["人很少", "清靜", "不擁擠", "人煙稀少", "幾乎沒人", "很空曠", "人少", "幾乎沒有人", "空曠"]
    },
    "accessibility": {
        "pos": ["步行即達", "交通方便", "出站即到", "很好找", "容易到", "交通便利", "走路可到", "很近", "非常近"],
        "neg": ["需要開車", "偏遠", "交通不便", "很難找", "交通不方便", "需自駕", "沒有大眾運輸",
                "很遠", "交通麻煩", "要自駕", "沒有公車", "包車", "租車才能到"]
    },
    "seasonal": {
        "neg": ["花季", "楓葉季", "期間限定", "只有夏天", "冬季才有", "只有春天", "限定季節",
                "特定季節", "梅花季", "紫藤季", "螢火蟲季", "賞楓", "賞花", "只在", "季節限定",
                "冬天限定", "夏天才有", "只有這個季節"]
    },
    "photo": {
        "pos": ["超好拍", "ig", "IG", "網美", "絕景", "好拍", "拍起來很美", "打卡", "必拍",
                "美爆", "超美", "景色絕美", "拍照聖地", "拍照很美", "取景", "很上鏡", "美景",
                "超級美", "美到", "真的很美", "景色很美", "風景很美"]
    },
    "value": {
        "pos": ["免費", "cp值高", "CP值高", "值得", "超值", "便宜", "划算", "性價比高",
                "不貴", "很划算", "CP值不錯", "免費參觀", "免費入場", "不收費"],
        "neg": ["有點貴", "不值得", "太貴", "cp值低", "CP值低", "貴", "坑錢", "門票貴",
                "很貴", "偏貴"]
    },
    "planning": {
        "neg": ["需要預約", "搶票", "限流", "一票難求", "要排隊預約", "很難訂", "提前預訂",
                "需要抽籤", "搶不到票", "要提前", "很難預約", "需要提前", "提前訂", "提早訂"]
    },
}


def extract_wide_context(text: str, entity: str, window: int) -> list[str]:
    """Find all occurrences of entity in text, return ±window char contexts."""
    contexts = []
    start = 0
    while True:
        idx = text.find(entity, start)
        if idx == -1:
            break
        lo = max(0, idx - window)
        hi = min(len(text), idx + len(entity) + window)
        contexts.append(text[lo:hi])
        start = idx + 1
    return contexts


def compute_dimensions(contexts: list[str], sent_scores: list[float]) -> dict[str, float]:
    n = len(contexts)
    if n == 0:
        return {d: 0.0 for d in DIM_KEYWORDS}

    scores = {}
    for dim, kw_dict in DIM_KEYWORDS.items():
        pos_kws = kw_dict.get("pos", [])
        neg_kws = kw_dict.get("neg", [])
        weighted_pos, weighted_neg = 0.0, 0.0
        for text, sent in zip(contexts, sent_scores):
            text_lower = text.lower()
            pos_hit = any(kw.lower() in text_lower for kw in pos_kws)
            neg_hit = any(kw.lower() in text_lower for kw in neg_kws)
            sentiment_weight = 1.0 - 0.4 * sent
            if pos_hit:
                weighted_pos += 1.0
            if neg_hit:
                weighted_neg += sentiment_weight
        scores[dim] = round((weighted_pos - weighted_neg) / n, 4)
    return scores


def main():
    conn = sqlite3.connect(DB_PATH)

    # load whitelisted spots and their sentiment scores
    spot_data = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT spot, sentiment_score, mention_count FROM spot_sentiment"
    )}
    log.info("Spots to recompute: %d", len(spot_data))

    # load post content
    post_content = {r[0]: r[1] for r in conn.execute(
        "SELECT id, content FROM posts WHERE content IS NOT NULL"
    )}

    # get post_ids per spot from ner_locations
    spot_posts: dict[str, list[str]] = defaultdict(list)
    for spot, post_id in conn.execute(
        "SELECT entity, post_id FROM ner_locations WHERE in_whitelist=1"
    ):
        spot_posts[spot].append(post_id)

    # build wide contexts for each spot
    updated = 0
    for spot, (avg_sent, mention_count) in spot_data.items():
        post_ids = spot_posts.get(spot, [])
        wide_contexts = []
        for pid in post_ids:
            content = post_content.get(pid, "")
            wide_contexts.extend(extract_wide_context(content, spot, CONTEXT_WIN))

        if not wide_contexts:
            continue

        # use avg_sent as proxy score for each context (we don't have per-context scores)
        proxy_scores = [avg_sent] * len(wide_contexts)
        dims = compute_dimensions(wide_contexts, proxy_scores)

        conn.execute("""
            UPDATE spot_sentiment
            SET dim_crowd=?, dim_access=?, dim_seasonal=?,
                dim_photo=?, dim_value=?, dim_planning=?
            WHERE spot=?
        """, (
            dims["crowd"], dims["accessibility"], dims["seasonal"],
            dims["photo"], dims["value"], dims["planning"],
            spot
        ))
        updated += 1

    conn.commit()
    log.info("Updated %d spots with ±%d char context dimensions", updated, CONTEXT_WIN)

    # summary
    print(f"\n── Six-dimension averages (±{CONTEXT_WIN} char) ──")
    dims = conn.execute("""
        SELECT AVG(dim_crowd), AVG(dim_access), AVG(dim_seasonal),
               AVG(dim_photo), AVG(dim_value), AVG(dim_planning)
        FROM spot_sentiment
    """).fetchone()
    labels = ["crowd", "access", "seasonal", "photo", "value", "planning"]
    for label, val in zip(labels, dims):
        print(f"  {label:<12} avg={val:+.4f}")

    print("\n── Top 10 高人潮壓力景點 ──")
    for row in conn.execute("""
        SELECT spot, dim_crowd, doc_freq FROM spot_sentiment
        ORDER BY dim_crowd ASC LIMIT 10
    """):
        print(f"  {row[0]:<20} crowd={row[1]:+.3f}  posts={row[2]}")

    print("\n── Top 10 高打卡價值景點 ──")
    for row in conn.execute("""
        SELECT spot, dim_photo, doc_freq FROM spot_sentiment
        ORDER BY dim_photo DESC LIMIT 10
    """):
        print(f"  {row[0]:<20} photo={row[1]:+.3f}  posts={row[2]}")

    print("\n── Top 10 高交通難度景點 ──")
    for row in conn.execute("""
        SELECT spot, dim_access, doc_freq FROM spot_sentiment
        ORDER BY dim_access ASC LIMIT 10
    """):
        print(f"  {row[0]:<20} access={row[1]:+.3f}  posts={row[2]}")

    conn.close()


if __name__ == "__main__":
    main()
