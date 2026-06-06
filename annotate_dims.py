"""
用 Gemma 3 4B 對每個景點的 context window 標注六維情感分數（-1 / 0 / 1）。
輸入：sample_150_ids.csv（文章 ID 清單）
輸出：dim_annotations.csv（每列 = 一篇文章 × 一個景點）
"""

import json
import time
import sqlite3
import requests
import logging
import csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH     = "japan_travel.db"
INPUT_CSV   = "sample_150_ids.csv"
OUTPUT_JSON = "dim_annotations.json"
OLLAMA_URL  = "http://localhost:11434/api/generate"
MODEL       = "gemma3:4b"
SLEEP_SEC   = 0.8

import re

def extract_spot_sentences(content: str, spot: str, padding: int = 1) -> str:
    """
    抽出文章中提及景點的句子，加上前後各 padding 句作為語境。
    比固定字元窗口更自然，不會切斷句子。
    """
    sentences = [s.strip() for s in re.split(r'[。！？\n]+', content) if s.strip()]
    result = []
    for i, sent in enumerate(sentences):
        if spot in sent:
            lo = max(0, i - padding)
            hi = min(len(sentences), i + padding + 1)
            chunk = "。".join(sentences[lo:hi])
            if chunk not in result:
                result.append(chunk)
    return "\n---\n".join(result) if result else ""


DIMS = {
    "crowd":    "人潮壓力（-1=非常擁擠排隊人多, 0=未提及或中性, 1=人少清靜舒適）",
    "access":   "交通便利（-1=偏遠需自駕包車很難到, 0=未提及或中性, 1=交通方便步行可達）",
    "seasonal": "季節限制（-1=有季節限定，例如花季/楓葉季/期間限定/只有夏天才有，0=未提及或中性, 1=全年皆宜無限制）",
    "photo":    "打卡價值（-1=不好拍沒特色, 0=未提及或中性, 1=絕景超好拍IG打卡聖地）",
    "value":    "CP值（-1=太貴不值得, 0=未提及或中性, 1=免費或超值划算）",
    "planning": "規劃難度（-1=需搶票預約非常難訂, 0=未提及或中性, 1=不需預約輕鬆安排）",
}

DIM_DEFS = "\n".join(f"- {k}：{v}" for k, v in DIMS.items())

PROMPT_TEMPLATE = """\
你是旅遊評論分析助理。以下是一段 PTT 日本旅遊文章中，關於景點「{spot}」的描述片段。

請針對六個體驗維度各給一個分數：
- -1：片段明確描述負向體驗
-  0：片段未提及此維度，或描述中性
-  1：片段明確描述正向體驗

維度定義：
{dim_defs}

特別注意：
- seasonal：只有當描述片段明確說「該景點本身只有特定季節才值得去或才有特色」時才給 -1（例如：「只有花季才值得去」、「楓葉季限定」、「螢火蟲季才有」）。注意：作者在聖誕節、冬天、夏天等季節造訪，或周圍有節日活動，並不代表景點有季節限制。如果景點全年都可以去，請給 0，不要因為文章的旅行時間或周圍句子的季節氛圍就給 -1。
- access：提到需要自駕、包車、沒有大眾運輸才能到的，給 -1；有提到步行可到、出站即到，給 1。
- planning：有提到需要預約、搶票、提前訂的，給 -1。

只輸出 JSON，不要有其他文字：
{{"crowd": <-1|0|1>, "access": <-1|0|1>, "seasonal": <-1|0|1>, "photo": <-1|0|1>, "value": <-1|0|1>, "planning": <-1|0|1>}}

---
景點：{spot}
描述片段：
{context}
"""


def call_gemma(prompt: str, retries: int = 3) -> dict | None:
    for attempt in range(retries):
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": MODEL, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0, "num_predict": 80}},
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json()["response"].strip()
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError(f"找不到 JSON：{text[:80]}")
            return json.loads(text[start:end])
        except Exception as e:
            log.warning(f"    第 {attempt+1} 次失敗：{e}")
            time.sleep(2)
    return None


def validate(result: dict) -> dict:
    return {d: (int(result[d]) if int(result.get(d, 0)) in (-1, 0, 1) else 0)
            for d in DIMS}


def main():
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        ids = [row["id"] for row in csv.DictReader(f)]

    conn = sqlite3.connect(DB_PATH)
    dim_keys = list(DIMS.keys())

    # 載入人工審查後的最終景點清單
    all_spots = [r[0] for r in conn.execute("SELECT spot FROM llm_spots_verified")]

    results = []
    total_articles = len(ids)

    for art_i, pid in enumerate(ids[:3], 1):
        post = conn.execute(
            "SELECT id, title FROM posts WHERE id=?", (pid,)
        ).fetchone()
        if not post:
            continue

        post_id, title = post
        content = conn.execute(
            "SELECT content FROM posts WHERE id=?", (post_id,)
        ).fetchone()[0] or ""

        spot_names = [s for s in all_spots if s in content]

        if not spot_names:
            log.info(f"[{art_i}/{total_articles}] {title[:35]} — 無景點，跳過")
            continue

        log.info(f"[{art_i}/{total_articles}] {title[:35]} — {len(spot_names)} 個景點")

        for spot in spot_names:
            context = extract_spot_sentences(content, spot, padding=1)
            if not context:
                continue

            prompt = PROMPT_TEMPLATE.format(
                spot=spot,
                dim_defs=DIM_DEFS,
                context=context[:600],
            )
            result = call_gemma(prompt)
            scores = validate(result) if result else {d: 0 for d in dim_keys}

            log.info(f"    {spot}: {scores}")
            results.append({
                "post_id": post_id,
                "title": title,
                "spot": spot,
                "context": context[:300],
                **scores,
            })

            # 每筆即時寫入，避免中途崩潰遺失
            with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            time.sleep(SLEEP_SEC)

    conn.close()
    log.info(f"完成，共 {len(results)} 筆，輸出：{OUTPUT_JSON}")


if __name__ == "__main__":
    main()
