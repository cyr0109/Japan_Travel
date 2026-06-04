"""
KKday 商業曝光驗證（Google Selenium + 自動重試版）

偵測到機器人檢查時，自動等待後重整，最多重試 MAX_BLOCK_RETRY 次。
不需要手動介入，可整夜放著跑。
"""

import os
import time
import random
import sqlite3
import logging
from urllib.parse import urlencode
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH          = "japan_travel.db"
SENTIMENT_MIN    = 0.6
DOC_FREQ_MAX     = 5
SLEEP_MIN        = 7.0
SLEEP_MAX        = 15.0
MAX_BLOCK_RETRY  = 5          # 最多重試幾次
BLOCK_WAIT       = [60, 120, 240, 480, 600]   # 每次被擋後等幾秒

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".chrome_scraper_profile")
_first_search_done = False


def ensure_columns(conn):
    cur = conn.cursor()
    existing = {r[1] for r in cur.execute("PRAGMA table_info(spot_sentiment)")}
    for col in ("kkday_exposed", "kkday_result_count"):
        if col not in existing:
            cur.execute(f"ALTER TABLE spot_sentiment ADD COLUMN {col} INTEGER")
    conn.commit()


NON_SPOTS = {
    # 食物飲料
    '蘋果汁','神戶牛','霜淇淋','哈密瓜','關東煮','五平餅','吉備糰子',
    '梅枝餅','福砂屋','廣島燒','一蘭','六花亭','金賞可樂餅',
    '麝香葡萄','冰淇淋','紫海膽','飛驒牛',
    # 動物角色品種
    '老虎','長頸鹿','仔虎','卡比獸','飛天史努比','潤水鴨','秋田犬',
    # 建築/地理通稱
    '天守','仁王門','三重塔','舞殿','護城河','游泳池','日本庭園',
    '二之丸庭園','西之丸','本殿','寶物殿','金色堂','八幡宮',
    '中央公園','道の駅','大國藥妝','櫻花樹','護城河',
    '日本海','馬場','市役所前','動物園',
}

def get_spots(conn):
    placeholders = ",".join("?" * len(NON_SPOTS))
    return conn.execute(f"""
        SELECT ss.spot, ss.sentiment_score
        FROM spot_sentiment ss
        JOIN llm_spots_clean lc ON ss.spot = lc.spot
        WHERE ss.sentiment_score > ?
          AND ss.doc_freq < ?
          AND ss.spot NOT IN ({placeholders})
          AND (ss.kkday_exposed IS NULL OR ss.kkday_exposed = -1)
        ORDER BY ss.sentiment_score DESC
    """, (SENTIMENT_MIN, DOC_FREQ_MAX, *NON_SPOTS)).fetchall()


def init_driver():
    global _first_search_done
    _first_search_done = False
    os.makedirs(PROFILE_DIR, exist_ok=True)
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument(f"--window-size={random.randint(1280,1440)},{random.randint(880,960)}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--lang=zh-TW")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW','zh','en-US']});
            window.chrome = { runtime: {} };
        """
    })
    return driver


def is_blocked(driver):
    src  = driver.page_source
    url  = driver.current_url
    return (
        "sorry" in driver.title.lower()
        or "captcha" in url
        or "sorry/index" in url
        or "consent.google" in url
        or len(src) < 8000
    )


def human_scroll(driver):
    for _ in range(random.randint(2, 4)):
        driver.execute_script(f"window.scrollBy(0, {random.randint(150, 400)})")
        time.sleep(random.uniform(0.3, 0.8))


def do_search(driver, query):
    """在 Google 執行搜尋（首次從首頁，之後從結果頁）。"""
    global _first_search_done
    if not _first_search_done:
        driver.get("https://www.google.com/")
        time.sleep(random.uniform(1.5, 2.5))
        try:
            box = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            box.clear()
            for ch in query:
                box.send_keys(ch)
                time.sleep(random.uniform(0.05, 0.13))
            time.sleep(random.uniform(0.4, 0.9))
            box.send_keys(Keys.RETURN)
            _first_search_done = True
        except Exception:
            q = urlencode({"q": query, "hl": "zh-TW"})
            driver.get(f"https://www.google.com/search?{q}")
            _first_search_done = True
    else:
        try:
            box = WebDriverWait(driver, 6).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            box.click()
            time.sleep(random.uniform(0.2, 0.5))
            driver.execute_script("arguments[0].value = '';", box)
            time.sleep(random.uniform(0.2, 0.4))
            for ch in query:
                box.send_keys(ch)
                time.sleep(random.uniform(0.05, 0.13))
            time.sleep(random.uniform(0.4, 0.8))
            box.send_keys(Keys.RETURN)
        except Exception:
            q = urlencode({"q": query, "hl": "zh-TW"})
            driver.get(f"https://www.google.com/search?{q}")


def extract_results(driver, spot):
    """從當前頁面 JS 抽取 KKday 結果。"""
    return driver.execute_script("""
        const results = [];
        const seenHrefs = new Set();
        document.querySelectorAll('a').forEach(a => {
            const href = a.href || '';
            if (!href.startsWith('https://www.kkday.com/zh-tw/product/')) return;
            if (seenHrefs.has(href)) return;
            seenHrefs.add(href);

            let h3 = a.querySelector('h3');
            if (!h3) {
                const p = a.closest('div');
                h3 = p ? p.querySelector('h3') : null;
            }
            if (!h3 || !h3.innerText.trim()) return;
            const title = h3.innerText.trim();

            let el = a, snippet = '';
            for (let i = 0; i < 12; i++) {
                el = el.parentElement;
                if (!el) break;
                const text = (el.innerText || '').trim();
                if (text.length < 800) { snippet = text; }
                else { break; }
            }
            results.push({ href, title, snippet });
        });
        return results;
    """)


def search_google(driver, spot):
    """搜尋並回傳 (exposed, result_count)，被擋時自動等待重試。"""
    query = f'kkday "{spot}"'

    for attempt in range(MAX_BLOCK_RETRY):
        try:
            do_search(driver, query)
            time.sleep(random.uniform(2.5, 4.0))

            if is_blocked(driver):
                wait = BLOCK_WAIT[min(attempt, len(BLOCK_WAIT) - 1)]
                log.warning(f"  ⚠️  被擋（第 {attempt+1} 次），等待 {wait}s 後重試...")
                time.sleep(wait)
                # 重整頁面，換個方向重試
                driver.get("https://www.google.com/")
                time.sleep(random.uniform(3, 6))
                global _first_search_done
                _first_search_done = False
                continue

            human_scroll(driver)
            items = extract_results(driver, spot)

            title_match   = [r for r in items if spot in r["title"]]
            snippet_match = [r for r in items if spot in r["snippet"] and spot not in r["title"]]
            exposed       = 1 if (title_match or snippet_match) else 0
            result_count  = len(title_match) + len(snippet_match)

            if title_match:
                log.info(f"  [{spot}] ✅ 標題命中 {len(title_match)} 個")
                for r in title_match[:2]:
                    log.info(f"    {r['title'][:60]}")
            if snippet_match:
                log.info(f"  [{spot}] ✅ 內文命中 {len(snippet_match)} 個")
                for r in snippet_match[:2]:
                    log.info(f"    {r['title'][:55]}")
            if not exposed:
                log.info(f"  [{spot}] ❌ 無曝光")

            return exposed, result_count

        except Exception as e:
            err = str(e)
            if "no such window" in err or "web view not found" in err:
                raise  # 讓外層重啟 driver
            log.warning(f"  例外（第 {attempt+1} 次）：{err[:80]}")
            time.sleep(random.uniform(10, 20))

    log.error(f"  [{spot}] 已達最大重試次數，跳過")
    return -1, -1


def save(conn, spot, exposed, count):
    conn.execute(
        "UPDATE spot_sentiment SET kkday_exposed=?, kkday_result_count=? WHERE spot=?",
        (exposed, count, spot)
    )
    conn.commit()


def print_summary(conn):
    rows = conn.execute("""
        SELECT ss.spot, ss.doc_freq, ss.sentiment_score, ss.kkday_exposed, ss.kkday_result_count
        FROM spot_sentiment ss
        JOIN llm_spots_clean lc ON ss.spot = lc.spot
        WHERE ss.sentiment_score > ? AND ss.doc_freq < ?
          AND ss.kkday_exposed IS NOT NULL AND ss.kkday_exposed >= 0
        ORDER BY ss.kkday_exposed ASC, ss.sentiment_score DESC
    """, (SENTIMENT_MIN, DOC_FREQ_MAX)).fetchall()

    print(f"\n{'景點':<18} {'篇數':>5} {'sentiment':>10} {'曝光':>6} {'命中':>5}")
    print("-" * 46)
    for spot, freq, sent, exp, cnt in rows:
        label = "✅" if exp == 1 else "❌"
        print(f"{spot:<18} {freq:>5} {sent:>10.4f} {label:>6} {cnt or 0:>5}")

    n_hidden  = sum(1 for *_, e, _ in rows if e == 0)
    n_exposed = sum(1 for *_, e, _ in rows if e == 1)
    print(f"\n隱藏景點：{n_hidden}　有曝光：{n_exposed}")


def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_columns(conn)
    spots = get_spots(conn)
    log.info(f"共 {len(spots)} 個景點（sentiment > {SENTIMENT_MIN}，doc_freq < {DOC_FREQ_MAX}）")

    driver = init_driver()
    try:
        for i, (spot, score) in enumerate(spots, 1):
            log.info(f"[{i}/{len(spots)}] {spot}（{score:.4f}）")
            try:
                exposed, count = search_google(driver, spot)
                save(conn, spot, exposed, count)
            except Exception as e:
                if "no such window" in str(e) or "web view not found" in str(e):
                    log.warning("  視窗異常，重啟 driver...")
                    try: driver.quit()
                    except: pass
                    time.sleep(5)
                    driver = init_driver()
                    try:
                        exposed, count = search_google(driver, spot)
                        save(conn, spot, exposed, count)
                    except Exception as e2:
                        log.error(f"  重啟後仍失敗：{e2}")
                        save(conn, spot, -1, -1)
                else:
                    log.error(f"  未知錯誤：{e}")
                    save(conn, spot, -1, -1)

            if i < len(spots):
                s = random.uniform(SLEEP_MIN, SLEEP_MAX)
                log.info(f"  等待 {s:.1f}s...")
                time.sleep(s)
    finally:
        try: driver.quit()
        except: pass
        conn.close()

    conn = sqlite3.connect(DB_PATH)
    print_summary(conn)
    conn.close()


if __name__ == "__main__":
    main()
