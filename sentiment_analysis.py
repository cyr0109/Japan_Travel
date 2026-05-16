"""
Sentiment analysis on NER context windows.
Model: lxyuan/distilbert-base-multilingual-cased-sentiments-student
Input: ner_locations.context (±50 chars around each entity mention)
Output: spot_sentiment table with per-spot sentiment score + six-dimension profile
"""

import sqlite3
import logging
import re
from collections import defaultdict
from math import log as math_log

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH    = "japan_travel.db"
BATCH_SIZE = 64
MAX_LEN    = 512

# ── Six-dimension keyword dictionary ────────────────────────────────────────
DIM_KEYWORDS = {
    "crowd": {
        "neg": ["排隊", "人山人海", "人擠人", "等很久", "大排長龍", "人超多", "很擠", "塞車", "塞滿"],
        "pos": ["人很少", "清靜", "不擁擠", "人煙稀少", "幾乎沒人", "很空曠", "人少"]
    },
    "accessibility": {
        "pos": ["步行即達", "交通方便", "出站即到", "很好找", "容易到", "交通便利", "走路可到"],
        "neg": ["需要開車", "偏遠", "交通不便", "很難找", "交通不方便", "需自駕", "沒有大眾運輸", "很遠"]
    },
    "seasonal": {
        "neg": ["花季", "楓葉季", "期間限定", "只有夏天", "冬季才有", "只有春天", "限定季節",
                "特定季節", "梅花季", "紫藤季", "螢火蟲季"]
    },
    "photo": {
        "pos": ["超好拍", "ig", "IG", "網美", "絕景", "好拍", "拍起來很美", "打卡", "必拍",
                "美爆", "超美", "景色絕美", "拍照聖地"]
    },
    "value": {
        "pos": ["免費", "cp值高", "CP值高", "值得", "超值", "便宜", "划算", "性價比高"],
        "neg": ["有點貴", "不值得", "太貴", "cp值低", "CP值低", "貴", "坑錢"]
    },
    "planning": {
        "neg": ["需要預約", "搶票", "限流", "一票難求", "要排隊預約", "很難訂", "提前預訂",
                "需要抽籤", "搶不到票"]
    },
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        DROP TABLE IF EXISTS spot_sentiment;
        CREATE TABLE spot_sentiment (
            spot            TEXT PRIMARY KEY,
            cluster_id      INTEGER,
            sentiment_score REAL,      -- avg positive probability (0-1)
            mention_count   INTEGER,   -- number of context windows
            doc_freq        INTEGER,   -- number of posts
            cluster_freq    INTEGER,   -- rank within cluster (doc_freq)
            dim_crowd       REAL,
            dim_access      REAL,
            dim_seasonal    REAL,
            dim_photo       REAL,
            dim_value       REAL,
            dim_planning    REAL,
            hidden_score    REAL       -- computed after sentiment
        );
        CREATE INDEX IF NOT EXISTS idx_sent_cluster ON spot_sentiment(cluster_id);
    """)
    conn.commit()


def load_contexts(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Return {entity: [context1, context2, ...]} for whitelisted spots."""
    spot_contexts: dict[str, list[str]] = defaultdict(list)
    for entity, context in conn.execute(
        "SELECT entity, context FROM ner_locations WHERE in_whitelist=1 AND context IS NOT NULL"
    ):
        if context and len(context.strip()) > 4:
            spot_contexts[entity].append(context.strip()[:MAX_LEN])
    log.info("Spots with contexts: %d", len(spot_contexts))
    return spot_contexts


def run_sentiment(spot_contexts: dict[str, list[str]]) -> dict[str, list[float]]:
    from transformers import pipeline

    log.info("Loading sentiment model…")
    pipe = pipeline(
        "sentiment-analysis",
        model="lxyuan/distilbert-base-multilingual-cased-sentiments-student",
        top_k=None,
        truncation=True,
        max_length=MAX_LEN,
    )

    spot_scores: dict[str, list[float]] = {}
    all_spots = list(spot_contexts.items())

    for i in range(0, len(all_spots), BATCH_SIZE):
        batch_spots = all_spots[i:i + BATCH_SIZE]

        # flatten contexts into one big batch
        flat_texts, flat_keys = [], []
        for spot, contexts in batch_spots:
            for ctx in contexts:
                flat_texts.append(ctx)
                flat_keys.append(spot)

        if not flat_texts:
            continue

        results = pipe(flat_texts, batch_size=BATCH_SIZE)
        for spot, result in zip(flat_keys, results):
            label_map = {r["label"]: r["score"] for r in result}
            pos_score = label_map.get("positive", 0.0)
            spot_scores.setdefault(spot, []).append(pos_score)

        if (i // BATCH_SIZE + 1) % 10 == 0:
            log.info("  %d / %d batches done", i // BATCH_SIZE + 1,
                     (len(all_spots) + BATCH_SIZE - 1) // BATCH_SIZE)

    return spot_scores


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
            # high-sentiment context → discount negative keyword impact
            sentiment_weight = 1.0 - 0.4 * sent
            if pos_hit:
                weighted_pos += 1.0
            if neg_hit:
                weighted_neg += sentiment_weight
        scores[dim] = round((weighted_pos - weighted_neg) / n, 4)
    return scores


def save_results(conn, spot_contexts, spot_scores):
    # load cluster assignments and doc_freq
    cluster_map = {r[0]: r[1] for r in conn.execute(
        "SELECT spot, cluster_id FROM spot_clusters"
    )}
    doc_freq_map = {r[0]: r[1] for r in conn.execute(
        "SELECT spot, doc_freq FROM spot_stats"
    )}

    rows = []
    for spot, contexts in spot_contexts.items():
        scores = spot_scores.get(spot, [])
        if not scores:
            continue
        avg_sent = round(sum(scores) / len(scores), 4)
        dims = compute_dimensions(contexts, scores)
        rows.append((
            spot,
            cluster_map.get(spot),
            avg_sent,
            len(scores),
            doc_freq_map.get(spot, 0),
            0,   # cluster_freq placeholder
            dims["crowd"],
            dims["accessibility"],
            dims["seasonal"],
            dims["photo"],
            dims["value"],
            dims["planning"],
            0.0, # hidden_score placeholder
        ))

    conn.executemany("""
        INSERT OR REPLACE INTO spot_sentiment
        (spot, cluster_id, sentiment_score, mention_count, doc_freq, cluster_freq,
         dim_crowd, dim_access, dim_seasonal, dim_photo, dim_value, dim_planning, hidden_score)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    log.info("Saved %d spots to spot_sentiment", len(rows))

    # compute cluster_freq rank and hidden_score
    clusters = {r[0] for r in conn.execute(
        "SELECT DISTINCT cluster_id FROM spot_sentiment WHERE cluster_id IS NOT NULL"
    )}
    for cid in clusters:
        spots = conn.execute("""
            SELECT spot, doc_freq FROM spot_sentiment
            WHERE cluster_id=? ORDER BY doc_freq ASC
        """, (cid,)).fetchall()
        if not spots:
            continue
        n = len(spots)
        q1_threshold = spots[max(0, int(n * 0.25) - 1)][1]

        for rank, (spot, df) in enumerate(spots):
            hs = 0.0
            sent = conn.execute(
                "SELECT sentiment_score FROM spot_sentiment WHERE spot=?", (spot,)
            ).fetchone()[0]
            if sent and df > 0:
                hs = round(sent * (1.0 / math_log(df + 1)), 4)
            conn.execute("""
                UPDATE spot_sentiment
                SET cluster_freq=?, hidden_score=?
                WHERE spot=?
            """, (df, hs, spot))
    conn.commit()


def print_summary(conn):
    total = conn.execute("SELECT COUNT(*) FROM spot_sentiment").fetchone()[0]
    avg_s = conn.execute("SELECT AVG(sentiment_score) FROM spot_sentiment").fetchone()[0]
    log.info("Total spots with sentiment: %d  | corpus avg sentiment: %.3f", total, avg_s or 0)

    print("\n── Top 20 by sentiment score (min 5 mentions) ──")
    rows = conn.execute("""
        SELECT spot, sentiment_score, mention_count, doc_freq, cluster_id
        FROM spot_sentiment
        WHERE mention_count >= 5
        ORDER BY sentiment_score DESC LIMIT 20
    """).fetchall()
    for spot, sent, mc, df, cid in rows:
        print(f"  {spot:<20} sent={sent:.3f}  mentions={mc:>4}  posts={df:>4}  cluster={cid}")

    print("\n── Top 20 hidden score (sentiment≥0.65, within cluster) ──")
    rows = conn.execute("""
        SELECT s.spot, s.sentiment_score, s.doc_freq, s.cluster_id, s.hidden_score
        FROM spot_sentiment s
        WHERE s.sentiment_score >= 0.65
        ORDER BY s.hidden_score DESC LIMIT 20
    """).fetchall()
    for spot, sent, df, cid, hs in rows:
        print(f"  {spot:<20} sent={sent:.3f}  posts={df:>4}  cluster={cid}  hidden={hs:.4f}")

    print("\n── Six-dimension averages (whitelisted spots) ──")
    dims = conn.execute("""
        SELECT AVG(dim_crowd), AVG(dim_access), AVG(dim_seasonal),
               AVG(dim_photo), AVG(dim_value), AVG(dim_planning)
        FROM spot_sentiment
    """).fetchone()
    labels = ["crowd", "access", "seasonal", "photo", "value", "planning"]
    for label, val in zip(labels, dims):
        print(f"  {label:<12} avg={val:.4f}" if val else f"  {label:<12} avg=0.0000")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-inference", action="store_true",
                        help="Skip model inference; recompute scores from existing spot_sentiment table")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    spot_contexts = load_contexts(conn)

    if args.skip_inference:
        log.info("Skipping inference — recomputing cluster_freq and hidden_score only")
        # reload scores from existing table
        spot_scores = {}
        for spot, sent, mc in conn.execute(
            "SELECT spot, sentiment_score, mention_count FROM spot_sentiment"
        ):
            spot_scores[spot] = [sent] * mc  # reconstruct approximate score list
    else:
        init_db(conn)
        spot_scores = run_sentiment(spot_contexts)

    save_results(conn, spot_contexts, spot_scores)
    print_summary(conn)
    conn.close()
