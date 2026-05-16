"""
NER pipeline: extract LOC entities from PTT Japan travel posts
Filters to [遊記][心得][分享] posts, runs CKIP NER, saves to SQLite.
"""

import sqlite3
import re
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = "japan_travel.db"
BATCH_SIZE = 32          # sentences per CKIP forward pass
MAX_SENT_LEN = 150       # chars; CKIP works best on shorter sentences
RELEVANT_TAGS = ("[遊記]", "[心得]", "[分享]")

# ── Generalised location tokens to reject ─────────────────────────────────────
STOPWORDS = {
    "日本", "東京", "大阪", "京都", "北海道", "九州", "沖繩", "名古屋",
    "福岡", "神奈川", "兵庫", "奈良", "廣島", "台灣", "機場", "飯店",
    "車站", "旅館", "hostel", "便利商店", "超市", "百貨", "商場",
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ner_locations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id     TEXT NOT NULL,
            entity      TEXT NOT NULL,
            context     TEXT,           -- ±50 chars around the entity
            sent_idx    INTEGER,        -- sentence index within post
            UNIQUE(post_id, entity, sent_idx)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ner_post ON ner_locations(post_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ner_entity ON ner_locations(entity)")
    conn.commit()


def load_posts(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return (id, content) for travel posts not yet NER-processed."""
    already = {r[0] for r in conn.execute("SELECT DISTINCT post_id FROM ner_locations")}
    rows = conn.execute("SELECT id, content FROM posts WHERE content IS NOT NULL").fetchall()

    result = []
    for pid, content in rows:
        if pid in already:
            continue
        title_row = conn.execute("SELECT title FROM posts WHERE id=?", (pid,)).fetchone()
        title = title_row[0] if title_row else ""
        if any(tag in title for tag in RELEVANT_TAGS):
            result.append((pid, content))
    log.info("Posts to process: %d", len(result))
    return result


def split_sentences(text: str) -> list[str]:
    """Split on punctuation; keep sentences ≤ MAX_SENT_LEN chars."""
    sents = re.split(r"[。！？\n]+", text)
    out = []
    for s in sents:
        s = s.strip()
        if not s:
            continue
        # further split long sentences on commas / semicolons
        if len(s) > MAX_SENT_LEN:
            for sub in re.split(r"[，、；,;]+", s):
                sub = sub.strip()
                if sub:
                    out.append(sub[:MAX_SENT_LEN])
        else:
            out.append(s)
    return out


def extract_context(sentence: str, entity: str, window: int = 50) -> str:
    idx = sentence.find(entity)
    if idx == -1:
        return sentence[:100]
    start = max(0, idx - window)
    end = min(len(sentence), idx + len(entity) + window)
    return sentence[start:end]


def run_ner(posts: list[tuple[str, str]], conn: sqlite3.Connection) -> None:
    from ckip_transformers.nlp import CkipNerChunker

    log.info("Loading CKIP NER model (first run downloads ~400 MB)…")
    ner = CkipNerChunker(model="bert-base")

    total_entities = 0
    insert_sql = """
        INSERT OR IGNORE INTO ner_locations (post_id, entity, context, sent_idx)
        VALUES (?, ?, ?, ?)
    """

    for post_idx, (pid, content) in enumerate(posts):
        sentences = split_sentences(content)
        if not sentences:
            continue

        # process in batches
        all_ner: list[list] = []
        for i in range(0, len(sentences), BATCH_SIZE):
            batch = sentences[i:i + BATCH_SIZE]
            all_ner.extend(ner(batch, batch_size=BATCH_SIZE))

        rows = []
        for sent_idx, (sentence, ner_result) in enumerate(zip(sentences, all_ner)):
            for entity, tag, _ in ner_result:
                if tag != "LOC":
                    continue
                # clean entity
                entity = entity.strip("「」『』【】〔〕()（）")
                if len(entity) < 2 or entity in STOPWORDS:
                    continue
                ctx = extract_context(sentence, entity)
                rows.append((pid, entity, ctx, sent_idx))

        if rows:
            conn.executemany(insert_sql, rows)
            conn.commit()
            total_entities += len(rows)

        if (post_idx + 1) % 100 == 0:
            log.info("  %d / %d posts done, %d entities so far",
                     post_idx + 1, len(posts), total_entities)

    log.info("Done. Total LOC entities inserted: %d", total_entities)


def print_summary(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM ner_locations").fetchone()[0]
    unique = conn.execute("SELECT COUNT(DISTINCT entity) FROM ner_locations").fetchone()[0]
    log.info("ner_locations rows: %d | unique entities: %d", total, unique)

    log.info("Top 20 most mentioned locations:")
    rows = conn.execute("""
        SELECT entity, COUNT(*) AS cnt, COUNT(DISTINCT post_id) AS posts
        FROM ner_locations
        GROUP BY entity
        ORDER BY posts DESC
        LIMIT 20
    """).fetchall()
    for entity, cnt, posts in rows:
        print(f"  {entity:<20} mentions={cnt:>5}  posts={posts:>4}")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    posts = load_posts(conn)
    if posts:
        run_ner(posts, conn)
    print_summary(conn)
    conn.close()
