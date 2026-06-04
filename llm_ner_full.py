import sqlite3
import json
import requests
import time
from collections import defaultdict

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"
OUTPUT_DB = "japan_travel.db"
BATCH_SAVE = 10  # 每 10 篇存一次進度

PROMPT_TEMPLATE = """你是一個旅遊景點抽取工具。請從以下 PTT 日本旅遊文章中，抽取所有旅客實際造訪或計畫造訪的「日本旅遊景點」名稱。

✅ 應該抽取：
- 神社、寺廟、大社、神宮（例：清水寺、伏見稻荷大社、嚴島神社）
- 自然景觀：山、湖、島、瀑布、溫泉、海灘、溪谷、岬角（例：富士山、河口湖）
- 人文景點：城堡、古蹟、公園、展望台、街道（例：姬路城、嵐山、哲學之道）
- 名稱必須用繁體中文

❌ 不應該抽取：
- 行政區、縣市、地區名（東京、大阪、京都、關西、北海道）
- 車站、機場（新幹線站名、機場）
- 飯店、旅館、民宿
- 餐廳、居酒屋、咖啡廳、食物名稱
- 購物中心、百貨公司、商店街
- 植物名稱（櫻花、紫藤、楓葉）
- 純日文名稱（必須有對應繁體中文才抽取）
- 非日本景點

輸出格式：只輸出 JSON 陣列，不要有任何說明文字。
例如：["清水寺", "伏見稻荷大社", "金閣寺"]
沒有景點則輸出：[]

文章內容：
{text}

JSON 陣列："""

EXCLUDE_KEYWORDS = [
    '車站', '機場', '電車', '新幹線', '飯店', '旅館', '民宿', '酒店',
    '餐廳', '居酒屋', '咖啡', '丼', '定食', '燒鳥', '壽司', '拉麵',
    '百貨', '購物', '商圈', '廣場',
]

def postprocess(spots: list) -> list:
    result = []
    for s in spots:
        s = str(s).strip()
        if not s or len(s) <= 1:
            continue
        if any(kw in s for kw in EXCLUDE_KEYWORDS):
            continue
        if s.startswith(('せ', 'で', 'み', 'あ', 'い', 'う', 'え', 'お')):
            continue
        result.append(s)
    return result

def call_ollama(text: str) -> list:
    payload = {
        "model": MODEL,
        "prompt": PROMPT_TEMPLATE.format(text=text[:1500]),
        "stream": False,
        "options": {"temperature": 0.0}
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=90)
        resp.raise_for_status()
        raw = resp.json()["response"].strip()
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        return postprocess(json.loads(raw[start:end]))
    except Exception:
        return []

def init_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_ner_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT,
            entity TEXT,
            UNIQUE(post_id, entity)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_ner_progress (
            post_id TEXT PRIMARY KEY,
            done INTEGER DEFAULT 0
        )
    """)
    conn.commit()

def get_done_ids(conn) -> set:
    cur = conn.execute("SELECT post_id FROM llm_ner_progress WHERE done=1")
    return {r[0] for r in cur.fetchall()}

def main():
    conn = sqlite3.connect(OUTPUT_DB)
    init_table(conn)

    done_ids = get_done_ids(conn)
    cur = conn.execute("""
        SELECT id, title, content FROM posts
        WHERE title LIKE '%[遊記]%' OR title LIKE '%[心得]%' OR title LIKE '%[分享]%'
    """)
    posts = cur.fetchall()
    remaining = [(pid, t, c) for pid, t, c in posts if str(pid) not in done_ids]

    total = len(posts)
    done = len(done_ids)
    print(f"總遊記：{total} 篇 | 已完成：{done} | 待處理：{len(remaining)}", flush=True)
    if not remaining:
        print("全部完成！", flush=True)
        return

    batch = []
    for i, (post_id, title, content) in enumerate(remaining):
        spots = call_ollama(content or "")

        batch.append((str(post_id), spots))

        processed = i + 1
        if processed % 10 == 0 or processed == len(remaining):
            elapsed_hint = f"{processed}/{len(remaining)}"
            unique = len(spots)
            print(f"[{elapsed_hint}] {title[:35]:<35} → {unique} 個景點: {spots[:5]}", flush=True)

        if len(batch) >= BATCH_SAVE or processed == len(remaining):
            for pid, spot_list in batch:
                for entity in spot_list:
                    conn.execute(
                        "INSERT OR IGNORE INTO llm_ner_locations (post_id, entity) VALUES (?, ?)",
                        (pid, entity)
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO llm_ner_progress (post_id, done) VALUES (?, 1)",
                    (pid,)
                )
            conn.commit()
            batch = []

    # 輸出統計
    cur = conn.execute("""
        SELECT entity, COUNT(DISTINCT post_id) as cnt
        FROM llm_ner_locations
        GROUP BY entity
        ORDER BY cnt DESC
        LIMIT 50
    """)
    print("\n=== Top 50 景點（依出現篇數）===")
    for entity, cnt in cur.fetchall():
        print(f"  {entity}: {cnt} 篇")

    conn.close()

if __name__ == "__main__":
    start_time = time.time()
    main()
    elapsed = (time.time() - start_time) / 60
    print(f"\n總耗時：{elapsed:.1f} 分鐘")
