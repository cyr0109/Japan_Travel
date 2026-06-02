"""
階段八：KKday 商業曝光驗證
用 Google 搜尋 `kkday "景點名"`，只採計 URL 為 kkday.com/zh-tw/product/
且標題包含景點名的結果，判斷該景點是否有 KKday 商業曝光。
結果寫入 spot_sentiment.kkday_exposed（0/1）與 kkday_result_count。
"""

import time
import sqlite3
import logging
from urllib.parse import urlencode
import undetected_chromedriver as uc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = "japan_travel.db"
HIDDEN_SCORE_THRESHOLD = 0.45
SLEEP_BETWEEN = 4.0
CHROME_VERSION = 148


def ensure_columns(conn: sqlite3.Connection):
    cur = conn.cursor()
    existing = {row[1] for row in cur.execute("PRAGMA table_info(spot_sentiment)")}
    if "kkday_exposed" not in existing:
        cur.execute("ALTER TABLE spot_sentiment ADD COLUMN kkday_exposed INTEGER")
    if "kkday_result_count" not in existing:
        cur.execute("ALTER TABLE spot_sentiment ADD COLUMN kkday_result_count INTEGER")
    conn.commit()


def get_spots(conn: sqlite3.Connection) -> list[tuple]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT spot, hidden_score
        FROM spot_sentiment
        WHERE hidden_score >= ?
        ORDER BY hidden_score DESC
        """,
        (HIDDEN_SCORE_THRESHOLD,),
    )
    return cur.fetchall()


def init_driver() -> uc.Chrome:
    opts = uc.ChromeOptions()
    opts.add_argument("--window-size=1280,900")
    return uc.Chrome(options=opts, version_main=CHROME_VERSION)


def search_kkday(driver: uc.Chrome, spot: str) -> tuple[int, int]:
    """
    回傳 (exposed, result_count)
    exposed = 1：Google 找到 kkday.com/zh-tw/product/ 頁面且標題包含景點名
    result_count：符合條件的結果數量
    """
    query = urlencode({"q": f'kkday "{spot}"', "hl": "zh-TW"})
    driver.get(f"https://www.google.com/search?{query}")
    time.sleep(3)

    # 用 JS 一次取出所有符合的連結，避免 stale element 問題
    results = driver.execute_script("""
        const items = [];
        document.querySelectorAll('a').forEach(a => {
            const href = a.href || '';
            if (!href.startsWith('https://www.kkday.com/zh-tw/product/')) return;
            const h3 = a.querySelector('h3');
            if (h3 && h3.innerText.trim()) {
                items.push({href: href, title: h3.innerText.trim()});
            }
        });
        return items;
    """)

    # 標題必須包含景點名才算有效曝光
    matched = [r for r in results if spot in r["title"]]
    result_count = len(matched)
    exposed = 1 if result_count > 0 else 0

    if exposed:
        log.info(f"  [{spot}] exposed=1，{result_count} 個產品標題含景點名")
        for r in matched[:3]:
            log.info(f"    - {r['title'][:60]}")
    else:
        log.info(f"  [{spot}] exposed=0")

    return exposed, result_count


def save_result(conn: sqlite3.Connection, spot: str, exposed: int, result_count: int):
    conn.execute(
        "UPDATE spot_sentiment SET kkday_exposed=?, kkday_result_count=? WHERE spot=?",
        (exposed, result_count, spot),
    )
    conn.commit()


def print_summary(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT spot, hidden_score, sentiment_score, kkday_exposed, kkday_result_count
        FROM spot_sentiment
        WHERE kkday_exposed IS NOT NULL
        ORDER BY hidden_score DESC
        """
    )
    rows = cur.fetchall()

    print(f"\n{'景點':<14} {'hidden_score':>12} {'sentiment':>10} {'KKday曝光':>10} {'產品數':>6}")
    print("-" * 58)
    for spot, hs, sent, exposed, cnt in rows:
        label = "✅ 有" if exposed == 1 else "❌ 無"
        print(f"{spot:<14} {hs:>12.4f} {sent:>10.4f} {label:>10} {cnt if cnt and cnt >= 0 else 'N/A':>6}")

    exposed_n = sum(1 for *_, e, _ in rows if e == 1)
    hidden_n  = sum(1 for *_, e, _ in rows if e == 0)
    print(f"\nKKday 有曝光：{exposed_n} 個　／　無曝光（真正隱藏）：{hidden_n} 個")


def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_columns(conn)
    spots = get_spots(conn)
    log.info(f"共 {len(spots)} 個景點待驗證（hidden_score ≥ {HIDDEN_SCORE_THRESHOLD}）")

    driver = init_driver()
    try:
        for i, (spot, score) in enumerate(spots, 1):
            log.info(f"[{i}/{len(spots)}] {spot}（hidden_score={score:.4f}）")
            try:
                exposed, result_count = search_kkday(driver, spot)
                save_result(conn, spot, exposed, result_count)
            except Exception as e:
                log.error(f"  [{spot}] 錯誤：{e}")
                save_result(conn, spot, -1, -1)

            if i < len(spots):
                time.sleep(SLEEP_BETWEEN)
    finally:
        driver.quit()
        conn.close()

    conn = sqlite3.connect(DB_PATH)
    print_summary(conn)
    conn.close()


if __name__ == "__main__":
    main()
