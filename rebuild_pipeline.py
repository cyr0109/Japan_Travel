"""
重建 pipeline：
1. 合併景點清單
2. 重建 PMI 共現網絡
3. 重跑 Louvain 社群偵測
4. 補情感分析（只跑新景點）
"""
import sqlite3
import math
import random
from itertools import combinations
from collections import defaultdict
from transformers import pipeline as hf_pipeline

DB = 'japan_travel.db'
conn = sqlite3.connect(DB)

print("=== Step 1：合併景點清單 ===")
ckip = set(r[0] for r in conn.execute('SELECT name_zh FROM spot_whitelist').fetchall())
llm  = set(r[0] for r in conn.execute('SELECT spot FROM llm_spots_clean').fetchall())
all_spots = ckip | llm
print(f"合併後總景點: {len(all_spots)} 個")

# ── Step 2：從 llm_ner_locations 重建共現 ────────────────
print("\n=== Step 2：重建 PMI 共現網絡 ===")

# 每篇文章有哪些景點
post_spots = defaultdict(set)
cur = conn.execute("""
    SELECT post_id, entity FROM llm_ner_locations
    WHERE entity IN ({})
""".format(','.join('?' * len(all_spots))), list(all_spots))

for post_id, entity in cur.fetchall():
    post_spots[post_id].add(entity)

print(f"有景點的文章數: {len(post_spots)}")

# 計算共現次數與文章頻率
spot_doc_freq = defaultdict(int)
pair_freq = defaultdict(int)
total_docs = len(post_spots)

for post_id, spots in post_spots.items():
    spots = list(spots)
    for s in spots:
        spot_doc_freq[s] += 1
    for a, b in combinations(sorted(spots), 2):
        pair_freq[(a, b)] += 1

print(f"景點文章頻率計算完成，共現對數: {len(pair_freq)}")

# 計算 PMI，過濾低頻
edges = []
for (a, b), cooccur in pair_freq.items():
    if cooccur < 3:
        continue
    pa = spot_doc_freq[a] / total_docs
    pb = spot_doc_freq[b] / total_docs
    pab = cooccur / total_docs
    pmi = math.log(pab / (pa * pb))
    if pmi > 0:
        edges.append((a, b, cooccur, round(pmi, 4)))

print(f"有效邊數 (cooccur≥3, PMI>0): {len(edges)}")

# 存入 DB
conn.execute('DELETE FROM cooccurrence_edges')
conn.executemany('INSERT INTO cooccurrence_edges VALUES (?,?,?,?)', edges)
conn.commit()
print("共現邊已更新")

# ── Step 3：Louvain 社群偵測 ────────────────────────────
print("\n=== Step 3：Louvain 社群偵測 ===")
import networkx as nx
import community as community_louvain

G = nx.Graph()
for a, b, cooccur, pmi in edges:
    G.add_edge(a, b, weight=pmi)

print(f"網絡節點數: {G.number_of_nodes()}, 邊數: {G.number_of_edges()}")

best_q, best_partition = -1, None
for seed in range(10):
    partition = community_louvain.best_partition(G, weight='weight', random_state=seed)
    q = community_louvain.modularity(partition, G, weight='weight')
    if q > best_q:
        best_q, best_partition = q, partition

print(f"Modularity Q = {best_q:.4f}")
print(f"群集數: {len(set(best_partition.values()))}")

# 更新 spot_clusters
conn.execute('DELETE FROM spot_clusters')
import networkx as nx
degree_cent = nx.degree_centrality(G)
between_cent = nx.betweenness_centrality(G, weight='weight')
clust_coef   = nx.clustering(G, weight='weight')

rows = []
for node, cluster_id in best_partition.items():
    rows.append((
        node, cluster_id,
        round(degree_cent.get(node, 0), 4),
        round(between_cent.get(node, 0), 4),
        round(clust_coef.get(node, 0), 4),
    ))
conn.executemany('INSERT INTO spot_clusters VALUES (?,?,?,?,?)', rows)
conn.commit()
print("spot_clusters 已更新")

# ── Step 4：補情感分析 ────────────────────────────────
print("\n=== Step 4：補情感分析（新景點）===")

already_done = set(r[0] for r in conn.execute('SELECT spot FROM spot_sentiment').fetchall())
new_spots_need_sentiment = [s for s in all_spots if s not in already_done and spot_doc_freq.get(s, 0) >= 3]
print(f"需要補情感分析: {len(new_spots_need_sentiment)} 個景點")

if new_spots_need_sentiment:
    sentiment_pipe = hf_pipeline(
        "sentiment-analysis",
        model="lxyuan/distilbert-base-multilingual-cased-sentiments-student",
        top_k=None
    )

    # 建立景點→語境文字的對應
    spot_contexts = defaultdict(list)
    cur = conn.execute('SELECT post_id, entity, context FROM ner_locations WHERE in_whitelist=1')
    for _, entity, context in cur.fetchall():
        if entity in new_spots_need_sentiment:
            spot_contexts[entity].append(context)

    # 從 llm_ner_locations 補語境（所有新景點都走這條路）
    posts_content = {str(r[0]): r[1] for r in conn.execute('SELECT id, content FROM posts').fetchall()}
    for spot in new_spots_need_sentiment:
        if len(spot_contexts[spot]) >= 5:
            continue
        cur = conn.execute('SELECT DISTINCT post_id FROM llm_ner_locations WHERE entity=?', (spot,))
        for (post_id,) in cur.fetchall()[:10]:
            content = posts_content.get(str(post_id), '') or ''
            idx = content.find(spot)
            if idx >= 0:
                context = content[max(0, idx-150):idx+300]
                spot_contexts[spot].append(context)

    inserted = 0
    for i, spot in enumerate(new_spots_need_sentiment):
        contexts = spot_contexts.get(spot, [])
        if not contexts:
            continue
        scores = []
        for ctx in contexts[:10]:
            try:
                result = sentiment_pipe(ctx[:512])
                label_map = {r['label']: r['score'] for r in result[0]}
                scores.append(label_map.get('positive', 0.0))
            except:
                pass
        if not scores:
            continue
        sentiment_score = sum(scores) / len(scores)
        doc_freq = spot_doc_freq.get(spot, 0)
        hidden_score = sentiment_score * (1 / math.log(doc_freq + 1)) if doc_freq > 0 else 0

        conn.execute('''
            INSERT OR REPLACE INTO spot_sentiment
            (spot, cluster_id, sentiment_score, doc_freq, hidden_score)
            VALUES (?, ?, ?, ?, ?)
        ''', (spot, best_partition.get(spot), round(sentiment_score, 4), doc_freq, round(hidden_score, 4)))

        inserted += 1
        if inserted % 50 == 0:
            conn.commit()
            print(f"  [{inserted}/{len(new_spots_need_sentiment)}] {spot}: {sentiment_score:.3f}", flush=True)

    conn.commit()
    print(f"情感分析完成，新增 {inserted} 個景點")

print("\n=== 完成 ===")
print(f"最終景點數: {conn.execute('SELECT COUNT(*) FROM spot_sentiment').fetchone()[0]}")
print(f"Modularity Q: {best_q:.4f}")
print(f"群集數: {len(set(best_partition.values()))}")
conn.close()
