"""
PTT Japan_Travel 版爬蟲
========================
策略：requests + BeautifulSoup，純靜態 HTML，不需要瀏覽器。

流程：
  Phase 1 — 從最新板頁往前翻頁，收集貼文 URL → CSV（同 japan_post_urls.csv）
  Phase 2 — 讀取 CSV，逐篇爬取標題/內文/推文 → DB（同 dcard_japan.db）

執行：
  python ptt_crawler.py --phase 1
  python ptt_crawler.py --phase 2
"""

import argparse
import csv
import re
import sqlite3
import time
import random
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── 設定 ──────────────────────────────────────────────────────
BOARD        = "Japan_Travel"
KEEP_TAGS    = {"遊記", "食記", "心得", "分享", "問題", "請益"}  # 只收這些標籤的文章
BASE_URL     = "https://www.ptt.cc"
CSV_PATH     = "japan_post_urls.csv"
DB_PATH      = "japan_travel.db"
MONTHS_BACK  = 48
MIN_DATE     = datetime.now(timezone.utc) - timedelta(days=MONTHS_BACK * 30)
REQUEST_DELAY = (0.05, 0.15)

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crawler.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

CSV_HEADER = ["post_id", "url", "forum", "queued_at", "post_date", "tag"]

_thread_local = threading.local()

def _sess() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.cookies.set("over18", "1", domain="www.ptt.cc")
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        })
        _thread_local.session = s
    return _thread_local.session


# ═══════════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════════

def get(url: str) -> Optional[BeautifulSoup]:
    for attempt in range(3):
        try:
            r = _sess().get(url, timeout=15)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "lxml")
            log.warning(f"HTTP {r.status_code}: {url}")
        except Exception as e:
            log.warning(f"請求失敗（第 {attempt+1} 次）：{e}")
        time.sleep(random.uniform(2, 4))
    return None


def load_csv_urls(csv_path: str) -> dict:
    p = Path(csv_path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8", newline="") as f:
        return {row["url"]: row for row in csv.DictReader(f)}


def append_to_csv(rows: list):
    p = Path(CSV_PATH)
    write_header = not p.exists()
    with open(p, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def ptt_url_to_id(url: str) -> Optional[str]:
    m = re.search(r"M\.(\d+)\.", url)
    return m.group(1) if m else None


# ═══════════════════════════════════════════════════════════════
# Phase 1 — 翻頁收集 URL
# ═══════════════════════════════════════════════════════════════

def parse_index_page(soup: BeautifulSoup) -> tuple[list, Optional[str]]:
    """回傳 ([(url, date_str), ...], 上一頁路徑)。只保留 KEEP_TAGS 標籤的文章。"""
    articles = []
    for ent in soup.select("div.r-ent"):
        a = ent.select_one("div.title a")
        if not a:
            continue
        title = a.text.strip()
        m = re.match(r'\[([^\]]+)\]', title)
        tag = m.group(1) if m else ""
        if tag not in KEEP_TAGS:
            continue
        href = a["href"]
        date_str = ent.select_one("div.date").text.strip()
        articles.append((BASE_URL + href, date_str, tag))

    prev = soup.select_one("div#action-bar-container a.btn:-soup-contains('上頁')")
    prev_path = prev["href"] if prev else None
    return articles, prev_path


def collect_ptt_urls():
    existing = load_csv_urls(CSV_PATH)
    existing_urls = set(existing.keys())
    now = datetime.now(timezone.utc).isoformat()
    total_new = 0

    index_url = f"{BASE_URL}/bbs/{BOARD}/index.html"
    log.info(f"開始從 {index_url} 往前收集...")

    while index_url:
        soup = get(index_url)
        if not soup:
            break

        articles, prev_path = parse_index_page(soup)
        if not articles:
            break

        page_new = []
        cutoff_count = 0
        page_dates = []

        for url, date_str, tag in articles:
            # 用 URL 裡的 Unix timestamp 判斷日期（最準確）
            post_id = ptt_url_to_id(url)
            try:
                dt = datetime.fromtimestamp(int(post_id), tz=timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)

            page_dates.append(dt)

            if dt < MIN_DATE:
                cutoff_count += 1
                continue

            if url in existing_urls:
                continue

            if not post_id:
                continue

            page_new.append({
                "post_id": post_id,
                "url": url,
                "forum": f"ptt_{BOARD}",
                "queued_at": now,
                "post_date": dt.strftime("%Y-%m-%d"),
                "tag": tag,
            })
            existing_urls.add(url)

        if page_new:
            append_to_csv(page_new)
            total_new += len(page_new)

        date_range = ""
        if page_dates:
            oldest = min(page_dates).strftime("%Y-%m-%d")
            newest = max(page_dates).strftime("%Y-%m-%d")
            date_range = f"  [{oldest} ~ {newest}]"

        log.info(f"  {index_url.split('/')[-1]}：+{len(page_new)} 篇，累計新增 {total_new} 篇{date_range}")

        # 整頁都超過截止日期 → 停止
        if cutoff_count >= len(articles) * 0.8:
            log.info("超過截止日期，停止收集")
            break

        if not prev_path:
            break

        index_url = BASE_URL + prev_path
        time.sleep(random.uniform(*REQUEST_DELAY))

    log.info(f"Phase 1 完成，新增 {total_new} 篇至 {CSV_PATH}")


# ═══════════════════════════════════════════════════════════════
# Phase 2 — 爬取文章內容
# ═══════════════════════════════════════════════════════════════

def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id            TEXT PRIMARY KEY,
            url           TEXT,
            title         TEXT,
            content       TEXT,
            forum         TEXT,
            like_count    INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            created_at    TEXT,
            crawled_at    TEXT,
            comments_fetched INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS comments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id    TEXT NOT NULL,
            content    TEXT,
            like_count INTEGER DEFAULT 0,
            floor      TEXT
        );
    """)
    conn.commit()
    return conn


def parse_ptt_date(time_str: str) -> str:
    """解析 PTT 時間格式：'Wed May 13 22:07:08 2026'"""
    try:
        dt = datetime.strptime(time_str.strip(), "%a %b %d %H:%M:%S %Y")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def scrape_article(url: str) -> Optional[dict]:
    soup = get(url)
    if not soup:
        return None

    main = soup.select_one("#main-content")
    if not main:
        return None

    # 標題、作者、時間
    title = ""
    created_at = ""
    for meta in main.select("div.article-metaline"):
        tag = meta.select_one("span.article-meta-tag")
        val = meta.select_one("span.article-meta-value")
        if not tag or not val:
            continue
        if "標題" in tag.text:
            title = val.text.strip()
        elif "時間" in tag.text:
            created_at = parse_ptt_date(val.text)

    # 移除 meta 區塊和推文，保留純內文
    for tag in main.select("div.article-metaline, div.article-metaline-right, "
                            "div.push, div#article-polling, span.f2"):
        tag.decompose()

    content = main.get_text("\n").strip()

    # 推文
    comments = []
    push_tag_map = {"推": 1, "→": 0, "噓": -1}
    for push in soup.select("div.push"):
        tag_el   = push.select_one("span.push-tag")
        user_el  = push.select_one("span.push-userid")
        cont_el  = push.select_one("span.push-content")
        if not cont_el:
            continue
        tag_text = tag_el.text.strip() if tag_el else ""
        like = push_tag_map.get(tag_text, 0)
        comments.append({
            "content": cont_el.text.lstrip(": ").strip(),
            "like_count": like,
            "floor": user_el.text.strip() if user_el else "",
        })

    return {
        "title": title,
        "content": content,
        "created_at": created_at,
        "like_count": sum(c["like_count"] for c in comments if c["like_count"] > 0),
        "comments": comments,
    }


def crawl_ptt_posts(worker: int = 0, workers: int = 1, threads: int = 10):
    conn = init_db()
    db_lock = threading.Lock()
    existing_ids = {str(r[0]) for r in conn.execute("SELECT id FROM posts").fetchall()}

    all_rows = load_csv_urls(CSV_PATH)
    pending = [
        (r["post_id"], r["url"], r["forum"])
        for r in all_rows.values()
        if r["forum"].startswith("ptt_") and r["post_id"] not in existing_ids
    ]
    pending.sort(key=lambda x: x[0], reverse=True)
    if workers > 1:
        pending = [p for i, p in enumerate(pending) if i % workers == worker]
        log.info(f"Worker {worker}/{workers}，負責 {len(pending)} 篇")

    total = len(pending)
    done = 0
    log.info(f"待爬 PTT 文章：{total} 篇（{threads} 執行緒）")

    def fetch_and_save(args):
        nonlocal done
        post_id, url, forum = args
        post = scrape_article(url)
        if not post:
            return f"✗ {url}"

        try:
            dt = datetime.fromisoformat(post["created_at"])
            if dt < MIN_DATE:
                return f"跳過（太舊）{url}"
        except Exception:
            pass

        with db_lock:
            conn.execute("""
                INSERT OR REPLACE INTO posts
                    (id, url, title, content, forum, like_count, comment_count,
                     created_at, crawled_at, comments_fetched)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (post_id, url, post["title"], post["content"], forum,
                  post["like_count"], len(post["comments"]),
                  post["created_at"], datetime.now(timezone.utc).isoformat(),
                  1 if post["comments"] else 0))
            if post["comments"]:
                conn.executemany(
                    "INSERT INTO comments (post_id, content, like_count, floor) VALUES (?,?,?,?)",
                    [(post_id, c["content"], c["like_count"], c["floor"])
                     for c in post["comments"]]
                )
            conn.commit()
            done += 1
        return f"✓ [{done}/{total}] {post['title'][:40]}  推文:{len(post['comments'])}"

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = {ex.submit(fetch_and_save, p): p for p in pending}
        for fut in as_completed(futures):
            log.info(fut.result())

    total_db = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE forum LIKE 'ptt_%'"
    ).fetchone()[0]
    log.info(f"Phase 2 完成，PTT 文章共 {total_db} 篇")
    conn.close()


# ═══════════════════════════════════════════════════════════════
# 主程式
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="PTT Japan_Travel 爬蟲")
    parser.add_argument("--phase", type=int, choices=[1, 2], required=True)
    parser.add_argument("--worker", type=int, default=0,
                        help="worker 編號，從 0 開始（配合 --workers 使用）")
    parser.add_argument("--workers", type=int, default=1,
                        help="總共幾個 worker（預設 1）")
    parser.add_argument("--threads", type=int, default=10,
                        help="每個 worker 的執行緒數（預設 10）")
    args = parser.parse_args()

    if args.phase == 1:
        collect_ptt_urls()
    else:
        crawl_ptt_posts(worker=args.worker, workers=args.workers, threads=args.threads)


if __name__ == "__main__":
    main()
