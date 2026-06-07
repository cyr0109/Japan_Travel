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

【核心原則】所有維度預設給 0。只有描述片段用明確的詞語描述正向或負向體驗時，才給 1 或 -1。不要推斷、不要根據常識猜測，只根據片段裡實際寫了什麼來判斷。

六個維度的評分標準：

crowd（人潮）：
  -1：明確說排隊、人山人海、人超多、很擠
   0：未提及，或只說「有一些人」、「人潮還好」等中性描述
   1：明確說人很少、清靜、幾乎沒人、空曠

access（交通）：
  -1：明確出現以下任一：「需要自駕」「需要包車」「需要租車」「沒有大眾運輸」「無大眾運輸」「距離大眾運輸有段距離」「交通不便」「交通不方便」「很難到」「很遠才能到」「只能開車」「只能自駕」「班次很少」「班次稀少」「偏遠」
   0：以下情況一律給 0：
      - context 完全未提到交通
      - 只說「搭電車去」「搭巴士去」「抵達車站」「從車站出發」（陳述交通方式，不等於方便）
      - 只說「自駕」「開車」而未說是「因為沒有大眾運輸才開車」
   1：明確出現以下任一：「步行即達」「出站即到」「出站就到」「走路幾分鐘就到」「走路可到」「走路5分」「走路10分」「走路15分」「步行約X分」「交通非常方便」「離車站很近」「就在車站旁」
   ⚠️ 不可根據景點名稱推斷交通難易度，只根據 context 文字判斷。

seasonal（季節限制）：
  -1：明確說該景點只有特定季節才值得去（花季、楓葉季、螢火蟲季、期間限定等）
   0：未提及季節限制，或只是作者剛好在某季節造訪（聖誕、冬天、夏天不算限制）
   1：不要給 1，幾乎沒有文章會明確說「全年皆宜」

photo（打卡價值）：
  -1：明確說不好拍、沒特色、拍起來很普通
   0：未提及，或只說「拍了幾張照片」、「景色還不錯」等普通描述
   1：明確說絕景、超好拍、IG 打卡聖地、景色非常美、必拍

value（CP 值）：
  -1：明確說太貴、不值得、很坑錢
   0：未提及，或只說「買了票」、「有收費」等中性描述
   1：明確說免費、超值、很划算、CP 值高

planning（規劃難度）：
  -1：明確說需要預約、搶票、一票難求、提前很久才能訂
   0：未提及
   1：不要給 1，幾乎沒有文章會明確說「不需預約」

只輸出 JSON，不要有其他文字：
{{"crowd": <-1|0|1>, "access": <-1|0|1>, "seasonal": <-1|0>, "photo": <-1|0|1>, "value": <-1|0|1>, "planning": <-1|0>}}

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
    scores = {}
    for d in DIMS:
        v = int(result.get(d, 0))
        v = v if v in (-1, 0, 1) else 0
        # seasonal 和 planning 的正向（=1）在旅遊文章中幾乎不存在，強制夾住到 0
        if d in ("seasonal", "planning") and v == 1:
            v = 0
        scores[d] = v
    return scores


def main():
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        ids = [row["id"] for row in csv.DictReader(f)]

    conn = sqlite3.connect(DB_PATH)
    dim_keys = list(DIMS.keys())

    # 載入人工審查後的最終景點清單
    all_spots = [r[0] for r in conn.execute("SELECT spot FROM llm_spots_verified")]

    results = []
    total_articles = len(ids)

    for art_i, pid in enumerate(ids, 1):
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
