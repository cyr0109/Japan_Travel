"""
Build PMI-weighted co-occurrence network from PTT travel posts.
Co-occurrence unit: day segment within a post.
Posts without day structure fall back to full-text co-occurrence.
Results saved to SQLite tables: cooccurrence_edges, spot_stats.
"""

import sqlite3
import re
import math
import logging
from collections import defaultdict
from itertools import combinations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = "japan_travel.db"
MIN_COOCCUR = 3   # minimum co-occurrence count to keep edge
MIN_PMI     = 0.0 # edges with PMI <= 0 are discarded

DAY_PATTERN = re.compile(
    r'(Day\s*\d+|第[一二三四五六七八九十百千]+天|D\s*\d+(?!\d)|dag\s*\d+)',
    re.IGNORECASE
)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        DROP TABLE IF EXISTS cooccurrence_edges;
        DROP TABLE IF EXISTS spot_stats;

        CREATE TABLE cooccurrence_edges (
            spot_a      TEXT NOT NULL,
            spot_b      TEXT NOT NULL,
            cooccur     INTEGER NOT NULL,
            pmi         REAL NOT NULL,
            PRIMARY KEY (spot_a, spot_b)
        );
        CREATE INDEX idx_edge_a ON cooccurrence_edges(spot_a);
        CREATE INDEX idx_edge_b ON cooccurrence_edges(spot_b);

        CREATE TABLE spot_stats (
            spot        TEXT PRIMARY KEY,
            doc_freq    INTEGER NOT NULL,   -- number of posts containing this spot
            total_posts INTEGER NOT NULL    -- total posts in corpus
        );
    """)
    conn.commit()


def split_by_day(text: str) -> list[str]:
    """Return list of day-segment strings; single-element list if no day markers."""
    parts = DAY_PATTERN.split(text)
    if len(parts) <= 1:
        return [text]
    # parts alternates: [before_day1, marker1, content1, marker2, content2, ...]
    segments = []
    i = 1
    while i < len(parts):
        marker  = parts[i]
        content = parts[i + 1] if i + 1 < len(parts) else ""
        segments.append(marker + content)
        i += 2
    return segments if segments else [text]


def build_cooccurrence(conn: sqlite3.Connection):
    whitelist = {r[0] for r in conn.execute("SELECT name_zh FROM spot_whitelist")}

    # load NER results grouped by post
    post_entities: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for post_id, entity, sent_idx in conn.execute(
        "SELECT post_id, entity, sent_idx FROM ner_locations WHERE in_whitelist=1"
    ):
        post_entities[post_id].append((sent_idx, entity))

    log.info("Posts with whitelisted entities: %d", len(post_entities))

    # load post content for day-segment splitting
    post_content: dict[str, str] = {}
    for pid, content in conn.execute(
        "SELECT id, content FROM posts WHERE content IS NOT NULL"
    ):
        post_content[pid] = content or ""

    # sentence index → approximate character offset (rough mapping)
    # We split content into sentences the same way ner_pipeline did
    sent_split = re.compile(r'[。！？\n]+')

    # track per-post spot sets (for document frequency)
    doc_freq: dict[str, int] = defaultdict(int)
    pair_freq: dict[tuple, int] = defaultdict(int)
    total_posts = len(post_entities)
    has_day_structure = 0

    for post_idx, (pid, ent_list) in enumerate(post_entities.items()):
        content = post_content.get(pid, "")
        segments = split_by_day(content)

        if len(segments) > 1:
            has_day_structure += 1

        # build sentence→segment mapping
        sentences = [s.strip() for s in sent_split.split(content) if s.strip()]
        sent_to_seg: dict[int, int] = {}
        char_offset = 0
        seg_boundaries = []
        for seg in segments:
            seg_boundaries.append(char_offset)
            char_offset += len(seg)

        for sent_i, sent in enumerate(sentences):
            # find which segment this sentence falls into
            pos = content.find(sent)
            seg_idx = 0
            for si, boundary in enumerate(seg_boundaries):
                if pos >= boundary:
                    seg_idx = si
            sent_to_seg[sent_i] = seg_idx

        # group entities by segment
        seg_entities: dict[int, set] = defaultdict(set)
        for sent_idx, entity in ent_list:
            seg_idx = sent_to_seg.get(sent_idx, 0)
            seg_entities[seg_idx].add(entity)

        # collect all spots in this post (for doc_freq)
        post_spots = set()
        for spots in seg_entities.values():
            post_spots.update(spots)
        for spot in post_spots:
            doc_freq[spot] += 1

        # build pairs within each segment
        for spots in seg_entities.values():
            spot_list = sorted(spots)
            for a, b in combinations(spot_list, 2):
                pair_freq[(a, b)] += 1

        if (post_idx + 1) % 500 == 0:
            log.info("  %d / %d posts processed", post_idx + 1, total_posts)

    log.info("Posts with day structure: %d / %d", has_day_structure, total_posts)
    log.info("Unique spots seen: %d", len(doc_freq))
    log.info("Unique pairs before filter: %d", len(pair_freq))

    return doc_freq, pair_freq, total_posts


def compute_pmi(doc_freq, pair_freq, total_posts):
    edges = []
    for (a, b), cooccur in pair_freq.items():
        if cooccur < MIN_COOCCUR:
            continue
        p_a   = doc_freq[a] / total_posts
        p_b   = doc_freq[b] / total_posts
        p_ab  = cooccur / total_posts
        pmi   = math.log(p_ab / (p_a * p_b))
        if pmi <= MIN_PMI:
            continue
        edges.append((a, b, cooccur, round(pmi, 4)))
    return edges


def save_results(conn, doc_freq, edges, total_posts):
    conn.executemany(
        "INSERT OR REPLACE INTO cooccurrence_edges VALUES (?,?,?,?)", edges
    )
    conn.executemany(
        "INSERT OR REPLACE INTO spot_stats VALUES (?,?,?)",
        [(spot, freq, total_posts) for spot, freq in doc_freq.items()]
    )
    conn.commit()


def print_summary(conn):
    n_edges = conn.execute("SELECT COUNT(*) FROM cooccurrence_edges").fetchone()[0]
    n_nodes = conn.execute("SELECT COUNT(DISTINCT spot_a) FROM cooccurrence_edges").fetchone()[0]
    avg_pmi = conn.execute("SELECT AVG(pmi) FROM cooccurrence_edges").fetchone()[0]
    log.info("Network: %d nodes, %d edges, avg PMI=%.3f", n_nodes, n_edges, avg_pmi or 0)

    log.info("Top 15 co-occurring pairs:")
    rows = conn.execute("""
        SELECT spot_a, spot_b, cooccur, pmi
        FROM cooccurrence_edges
        ORDER BY cooccur DESC LIMIT 15
    """).fetchall()
    for a, b, co, pmi in rows:
        print(f"  {a} — {b:<20} cooccur={co:>4}  PMI={pmi:.3f}")

    log.info("Top 15 by PMI (min cooccur=5):")
    rows = conn.execute("""
        SELECT spot_a, spot_b, cooccur, pmi
        FROM cooccurrence_edges
        WHERE cooccur >= 5
        ORDER BY pmi DESC LIMIT 15
    """).fetchall()
    for a, b, co, pmi in rows:
        print(f"  {a} — {b:<20} cooccur={co:>4}  PMI={pmi:.3f}")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    doc_freq, pair_freq, total_posts = build_cooccurrence(conn)
    edges = compute_pmi(doc_freq, pair_freq, total_posts)

    log.info("Edges after PMI filter (count≥%d, PMI>%.1f): %d", MIN_COOCCUR, MIN_PMI, len(edges))
    save_results(conn, doc_freq, edges, total_posts)
    print_summary(conn)
    conn.close()
