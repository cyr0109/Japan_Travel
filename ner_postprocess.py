import sqlite3
import re

conn = sqlite3.connect('japan_travel.db')

# ── 過濾規則 ──────────────────────────────────────────
CITY_NAMES = {
    '東京', '大阪', '京都', '北海道', '沖繩', '福岡', '名古屋', '札幌', '橫濱',
    '神戶', '廣島', '仙台', '金澤', '奈良', '長崎', '熊本', '鹿兒島', '松山',
    '高松', '德島', '高知', '那霸', '宜野灣', '浦添', '沖繩市', '石垣',
    '關西', '關東', '東北', '九州', '四國', '中部', '北陸', '東海',
    '日本', '台灣', '韓國', '中國', '歐洲', '亞洲', '美國',
    '東京都', '大阪府', '京都府',
}

NOISE_KEYWORDS = [
    '飯店', '旅館', '民宿', '酒店', 'hotel', 'Hotel',
    '餐廳', '居酒屋', '咖啡', '料理', '食堂', '拉麵', '壽司', '燒肉',
    '百貨', '購物', '商場', '超市', 'mall', 'Mall',
    '車站', '機場', '新幹線', '巴士', '電車',
    '醫院', '學校', '公司',
    'Uniqlo', 'AEON', 'PARCO',   # 購物品牌
]

EXACT_NOISE = {
    # 植物泛稱
    '櫻花', '楓葉', '紫藤', '紫陽花', '八重櫻', '九重葛', '山茶花',
    '染井吉野', '銀杏大道', '鹽竈櫻', '波波草', '大楠', '梅林', '梅苑',
    # 食物（含地方名產）
    '可頌', '泡芙', '抹茶', '烏龍麵', '鮪魚', '沙拉', '湯咖哩',
    '鰤魚', '河豚', '鳥取和牛', '佐賀牛', '稻庭烏龍麵', '馬肉刺身',
    '玄品河豚', '赤福', '成吉思汗烤肉', '喜助', '根室花丸',
    '熱田蓬萊軒', '博多麵街道', '二十世紀梨', '橘子', '水母',
    # 動漫/遊戲/角色
    '咒術迴戰', '薩爾達傳說', '動物森友會', '冰雪奇緣', '鬼太郎',
    '瑪莉歐', '馬力歐園區', '基拉祈', '呆火鱷', '伊布', '百變怪',
    '好萊塢',
    # 動物
    '大象', '北極熊', '迷你馬',
    # 泛化設施/物件
    '城堡', '瞭望塔', '石燈籠', '雲霄飛車', '足湯', '溫室',
    '見晴台', '御守', '神門', '市役所', '環球', '城堡',
    '溜滑梯', '水晶宮', '沉下橋', '女岩', '就實之丘',
    '千櫻橋', '海上鳥居', '小神社', '狛犬', '惠比須',
    '親子之木', '石燈籠', '火山口', '紅葉',
    # 連鎖品牌/餐飲
    '麥當勞', 'Uniqlo', 'AEON', 'PARCO', '松屋', 'Blue Seal冰淇淋',
    # 純日文無對應
    '円万寺観音堂', '駒ヶ岳',
    # 車站/交通
    '十字街站', '富士山站', '強羅站', '富山站', '旭川站', '貴志站',
    '關西空港', '百合海鷗號',
    # 縣市/地區
    '埼玉', '梅田',
    # 泛化
    '合掌屋', '有田燒',
}

NOISE_PATTERNS = [
    r'^[A-Za-z\s]+$',        # 純英文（但保留已知景點）
    r'^\d',                   # 數字開頭
    r'^.{1}$',                # 單字
    r'^.{20,}$',              # 超過20字（太長通常是句子）
]

WHITELIST_OVERRIDE = {
    'SHIBUYA SKY', 'Shibuya Sky', 'shibuya sky',
    '21世紀美術館', '北海道大學',
}

def is_noise(entity: str) -> bool:
    if entity in WHITELIST_OVERRIDE:
        return False
    if entity in CITY_NAMES:
        return True
    if entity in EXACT_NOISE:
        return True
    if any(kw in entity for kw in NOISE_KEYWORDS):
        return True
    for pattern in NOISE_PATTERNS:
        if re.match(pattern, entity):
            return True
    return False

# ── 套用過濾，門檻 ≥ 3 篇 ──────────────────────────────
cur = conn.execute('''
    SELECT entity, COUNT(DISTINCT post_id) as cnt
    FROM llm_ner_locations
    GROUP BY entity
    HAVING cnt >= 3
    ORDER BY cnt DESC
''')
all_entities = cur.fetchall()

clean = [(e, c) for e, c in all_entities if not is_noise(e)]
noise = [(e, c) for e, c in all_entities if is_noise(e)]

print(f'原始 (≥3篇): {len(all_entities)} 個')
print(f'過濾後保留: {len(clean)} 個')
print(f'過濾掉: {len(noise)} 個')

print(f'\n=== Top 80 保留景點 ===')
for entity, cnt in clean[:80]:
    print(f'  {entity:<15} {cnt} 篇')

print(f'\n=== 被過濾的前30個（確認是否誤殺）===')
for entity, cnt in noise[:30]:
    print(f'  {entity:<15} {cnt} 篇')

# ── 存進新表 ──────────────────────────────────────────
conn.execute('DROP TABLE IF EXISTS llm_spots_clean')
conn.execute('''
    CREATE TABLE llm_spots_clean (
        spot TEXT PRIMARY KEY,
        doc_freq INTEGER
    )
''')
conn.executemany(
    'INSERT INTO llm_spots_clean (spot, doc_freq) VALUES (?, ?)',
    clean
)
conn.commit()
print(f'\n已存入 llm_spots_clean 表：{len(clean)} 個景點')
