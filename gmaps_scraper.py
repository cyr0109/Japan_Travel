"""
Google Maps 評論數驗證
搜尋「景點名 日本」，從 Knowledge Panel 抓評論數。
評論數 < HIDDEN_THRESHOLD → 判定為真正隱藏景點。
"""

import os
import re
import time
import random
import sqlite3
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH          = "japan_travel.db"
HIDDEN_THRESHOLD = 2000
SLEEP_MIN        = 5.0
SLEEP_MAX        = 10.0
PROFILE_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".chrome_scraper_profile")

_first_search_done = False


def get_spots(conn):
    return conn.execute("""
        SELECT ss.spot, ss.sentiment_score
        FROM spot_sentiment ss
        JOIN llm_spots_clean lc ON ss.spot = lc.spot
        WHERE ss.sentiment_score > 0.6
          AND ss.doc_freq < 5
          AND ss.kkday_exposed = 0
          AND (ss.gmaps_reviews IS NULL OR ss.gmaps_reviews = 0)
        ORDER BY ss.sentiment_score DESC
    """).fetchall()


def init_driver():
    global _first_search_done
    _first_search_done = False
    os.makedirs(PROFILE_DIR, exist_ok=True)
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument(f"--window-size={random.randint(1280,1440)},{random.randint(880,960)}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=zh-TW")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW','zh','en-US']});
            window.chrome = { runtime: {} };
        """
    })
    return driver


def is_blocked(driver):
    url = driver.current_url
    return (
        "sorry" in driver.title.lower()
        or "captcha" in url
        or "sorry/index" in url
        or len(driver.page_source) < 8000
    )


def extract_review_count(driver):
    """從 Google Maps 地點詳情面板的 role=img span 精確抓評論數。"""
    return driver.execute_script("""
        // Google Maps 評論數格式：<span role="img" aria-label="4,610 則評論">
        const badges = document.querySelectorAll('[role="img"][aria-label]');
        for (const el of badges) {
            const label = el.getAttribute('aria-label') || '';
            const m = label.match(/([\d,，]+)\s*(則評論|reviews?|個評論|条评论)/i);
            if (m) {
                const n = parseInt(m[1].replace(/,|，/g, ''), 10);
                if (n > 0) return n;
            }
        }
        return null;
    """)


def find_search_box(driver):
    """嘗試多種 selector 找到 Google Maps 搜尋框。"""
    selectors = [
        (By.ID, "searchboxinput"),
        (By.CSS_SELECTOR, "input[name='q']"),
        (By.CSS_SELECTOR, "input[aria-label*='搜尋']"),
        (By.CSS_SELECTOR, "input[aria-label*='Search']"),
        (By.CSS_SELECTOR, "#searchbox input"),
        (By.CSS_SELECTOR, "input[type='text']"),
    ]
    for by, sel in selectors:
        try:
            el = WebDriverWait(driver, 4).until(
                EC.presence_of_element_located((by, sel))
            )
            if el.is_displayed():
                return el
        except Exception:
            continue
    return None


def search_and_get_reviews(driver, spot):
    """在 Google Maps 搜尋框輸入景點名，等待地點面板出現後抓評論數。"""
    try:
        driver.get("https://www.google.com/maps/")
        time.sleep(random.uniform(2.5, 3.5))

        box = find_search_box(driver)
        if not box:
            log.warning("  找不到搜尋框")
            return -1

        box.click()
        time.sleep(random.uniform(0.3, 0.5))
        driver.execute_script("arguments[0].value = '';", box)
        time.sleep(random.uniform(0.2, 0.3))

        for ch in spot:
            box.send_keys(ch)
            time.sleep(random.uniform(0.07, 0.15))

        time.sleep(random.uniform(0.6, 1.0))
        box.send_keys(Keys.RETURN)
        time.sleep(random.uniform(3.0, 4.0))

        # 若出現搜尋結果列表，點第一筆進入詳情頁
        clicked = driver.execute_script("""
            // 找搜尋結果列表的第一個地點連結
            const sel = [
                'a[href*="/maps/place/"]',
                '[data-result-index="0"] a',
                '.Nv2PK:first-child a',
            ];
            for (const s of sel) {
                const el = document.querySelector(s);
                if (el) { el.click(); return true; }
            }
            return false;
        """)
        if clicked:
            time.sleep(random.uniform(3.0, 4.0))

        count = extract_review_count(driver)
        return count if count is not None else 0

    except Exception as e:
        log.warning(f"  例外：{str(e)[:100]}")
        return -1


def save(conn, spot, reviews):
    conn.execute(
        "UPDATE spot_sentiment SET gmaps_reviews=? WHERE spot=?",
        (reviews, spot)
    )
    conn.commit()


def print_summary(conn):
    rows = conn.execute("""
        SELECT ss.spot, ss.doc_freq, ss.sentiment_score,
               ss.gmaps_reviews, ss.kkday_exposed
        FROM spot_sentiment ss
        JOIN llm_spots_clean lc ON ss.spot = lc.spot
        WHERE ss.sentiment_score > 0.6
          AND ss.doc_freq < 5
          AND ss.kkday_exposed = 0
          AND ss.gmaps_reviews IS NOT NULL
        ORDER BY ss.gmaps_reviews ASC
    """).fetchall()

    print(f"\n{'景點':<20} {'篇':>4} {'sentiment':>10} {'GMaps評論':>10} {'判定':>6}")
    print("-" * 58)
    hidden = []
    for spot, freq, sent, reviews, _ in rows:
        label = "🌟 隱藏" if (reviews is not None and 0 <= reviews < HIDDEN_THRESHOLD) else "主流"
        r_str = str(reviews) if reviews is not None and reviews >= 0 else "?"
        print(f"{spot:<20} {freq:>4} {sent:>10.4f} {r_str:>10} {label:>6}")
        if reviews is not None and 0 <= reviews < HIDDEN_THRESHOLD:
            hidden.append((spot, freq, sent, reviews))

    print(f"\n🌟 真正隱藏景點（GMaps < {HIDDEN_THRESHOLD}）：{len(hidden)} 個")
    for spot, freq, sent, rev in hidden:
        print(f"   {spot}：{rev} 則評論，PTT {freq} 篇，sentiment {sent:.4f}")


def main():
    conn = sqlite3.connect(DB_PATH)
    spots = get_spots(conn)
    log.info(f"共 {len(spots)} 個景點待查 Google Maps 評論數")

    driver = init_driver()
    try:
        for i, (spot, score) in enumerate(spots, 1):
            log.info(f"[{i}/{len(spots)}] {spot}")
            reviews = search_and_get_reviews(driver, spot)
            if reviews == -1:
                time.sleep(random.uniform(15, 25))
                reviews = search_and_get_reviews(driver, spot)
            save(conn, spot, reviews if reviews != -1 else None)
            label = f"🌟 {reviews}" if (reviews is not None and 0 <= reviews < HIDDEN_THRESHOLD) else str(reviews)
            log.info(f"  評論數：{label}")

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
