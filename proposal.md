# 期末專題研究提案

**從 PTT 日本板社群共現網絡挖掘日本景點隱藏偏好：行程群集、體驗側寫與商業缺口分析**

*Uncovering Hidden Travel Preferences from PTT Japan Board Co-occurrence Networks: Cluster Detection, Experience Profiling, and Commercial Gap Analysis*

Social Media Analytics | Spring 2026

---

## 一、研究動機

KKday、Klook 等旅遊平台的景點曝光由銷售邏輯主導，高佣金與廣告預算決定了哪些景點出現在首頁。這套機制對熱門景點有自我強化效果，卻系統性地忽略了社群評價高但難以標準化的景點——例如交通偏遠、只有特定季節值得去、或需要提前搶票的地方。

PTT 日本板（批踢踢 Japan 板）是台灣旅客分享日本旅遊行程的長期主要社群，累積大量真實出遊記錄，其文章隱含兩類商業平台無法取代的情報：一是**景點共現邏輯**，旅客把哪些景點排在同一天；二是**體驗評價**，哪些景點在實際走訪後仍獲正面描述。

本研究透過社群網絡分析從這兩類情報中系統性地萃取「隱藏版景點」——定義為社群評價高但在商業平台曝光不足的景點——並進一步分析這些景點在哪些體驗維度上有別於主流景點，試圖解釋「為什麼高評價景點仍被商業平台忽略」這個問題。分析結果最終轉化為可供旅遊平台使用的行程缺口偵測工具。

---

## 二、研究主題與問題

### 2.1 核心研究問題

- **RQ1**：PTT 日本板的日本景點共現網絡中，可透過 Louvain 社群偵測歸納出哪些隱性行程群集？各群集的 Modularity Q 值是否達 0.3 以上（代表群集結構顯著）？

- **RQ2**：隱藏版景點與非隱藏版景點在六個體驗維度（人潮壓力、交通可及性、季節限制、打卡價值、CP 值感知、規劃難度）上是否存在系統性差異？哪些維度最能區分兩類景點，揭示景點被商業平台低曝光的潛在原因？

- **RQ3**：在各行程群集內，情感分數 ≥ 0.65 且出現頻率低於群集第 25 百分位數（Q1）的景點，是否確實符合「社群高評價、商業低曝光」的定義（以景點名稱是否出現於 KKday 任何產品標題作為商業曝光代理指標）？

### 2.2 研究方法設計

三個 RQ 依序遞進：RQ1 建立網絡結構，RQ3 在該結構內識別隱藏版景點，RQ2 解釋這些景點為何被商業平台忽略。

| 階段 | 方法 | 對應課程主題 |
|------|------|-------------|
| 階段一 | 資料收集與前處理 | Text Mining (Week 3) |
| 階段二 | NER 地名擷取 + PMI 加權共現網絡 | Text Mining (Week 3) |
| 階段三 | Louvain 社群偵測（對應 RQ1） | Community Detection (Week 5) |
| 階段四 | 情感分析 + 六維體驗側寫（對應 RQ2） | Sentiment Analysis (Week 8/10) |
| 階段五 | 隱藏版景點識別與商業曝光驗證（對應 RQ3） | Marketing Intelligence (Week 11) |
| 階段六 | 行程缺口偵測工具（B2B Demo） | Marketing Intelligence (Week 11) |

---

## 三、資料取得

### 3.1 主要資料來源：PTT 日本板

透過爬取 PTT 日本板（`https://www.ptt.cc/bbs/Japan/`）公開網頁抓取文章，預計收集 **3,000–5,000 篇**，抓取欄位包含標題、內文、推文（推/噓/→）、推文數與發文時間，時間範圍為近 12 個月。PTT 網頁為靜態 HTML，無限流機制，以 `requests` + `BeautifulSoup` 即可穩定爬取，需攜帶 `over18=1` cookie 通過年齡驗證。

```python
import requests
from bs4 import BeautifulSoup

SESSION = requests.Session()
SESSION.cookies.set('over18', '1', domain='www.ptt.cc')
BASE_URL = 'https://www.ptt.cc'

def fetch_index(board: str, page: int) -> BeautifulSoup:
    url = f'{BASE_URL}/bbs/{board}/index{page}.html'
    resp = SESSION.get(url, timeout=10)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, 'html.parser')

def fetch_post(url: str) -> BeautifulSoup:
    resp = SESSION.get(BASE_URL + url, timeout=10)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, 'html.parser')
```

**爬取流程**：先從索引頁取得文章連結清單，再逐篇抓取內文與推文；每次請求間隔 0.5–1 秒，避免對伺服器造成負擔。推文以 `◆`（推）/`←`（噓）/`→`（→）標記，可作為社群反應的輔助情感訊號。

### 3.2 輔助資料來源

| 資料來源 | 用途 | 可及性 |
|---------|------|--------|
| KKday 產品標題（爬取） | 商業曝光代理指標，判斷景點是否出現於任何產品標題 | 公開網頁，需爬蟲 |
| 日本文化廳 国指定文化財データベース（kunishitei.bunka.go.jp） | 神社寺廟類景點白名單，篩選「史跡」「名勝」類別 | 公開網頁，需爬蟲 |
| WikiData SPARQL 查詢 | 自然景點白名單，查詢 `instance of: tourist attraction, located in Japan`，附帶座標 | 免費結構化資料，可直接下載 |

**WikiData 查詢範例**：

```sparql
SELECT ?spot ?spotLabel ?coord WHERE {
  ?spot wdt:P31/wdt:P279* wd:Q570116 .  # tourist attraction
  ?spot wdt:P17 wd:Q17 .                 # located in Japan
  ?spot wdt:P625 ?coord .                # 附帶經緯度座標
  SERVICE wikibase:label {
    bd:serviceParam wikibase:language "zh-tw,ja,en".
  }
}
```

WikiData 同時提供景點座標，可直接用於後續的地理距離計算，不需另外 Geocoding。

### 3.3 研究範圍

| 面向 | 定義 |
|------|------|
| 目的地 | 日本（全國） |
| 景點類型 | 自然景點（山、湖、瀑布、秘境）＋ 神社寺廟 |
| 排除 | 美食、購物、飯店、車站等交通節點 |
| 資料時間範圍 | 近 12 個月 |

### 3.4 資料前處理

- 去除廣告文、問卷文、非旅遊相關貼文
- 文字清洗：網址移除、重複字元壓縮；**表情符號轉文字**（使用 `emoji` 套件，如 😭→「極度悲傷」、🔥→「火焰」），保留情感訊號後再進行後續分析
- 語言篩選：保留繁體中文貼文
- 中文斷詞：使用 CKIP Tagger（中研院）

---

## 四、研究方法

### 4.1 地名實體辨識與景點白名單

使用 CKIP NER 模型擷取 LOC 類型詞彙，對照景點白名單過濾縣市層級的泛化地名（如「日本」「東京」）。白名單以兩個結構化來源為基底：

- **神社寺廟**：爬取文化廳 国指定文化財データベース，篩選「史跡」「特別史跡」「名勝」「特別名勝」類別，保留具明確地點的神社寺廟條目，並對應台灣旅客常用的中文稱呼
- **自然景點**：以 WikiData SPARQL 查詢 `tourist attraction located in Japan`，取得景點名稱與座標，人工篩除非自然景點類別

兩份名單合併後（預計約 400 個景點），再對初步爬取的貼文執行 NER，統計不在白名單內的高頻 LOC 詞彙，取前 50 名人工標記——此步驟最能捕捉 WikiData 與文化廳資料庫未收錄的新興景點（如近年爆紅的秘境或 IG 打卡地）。

### 4.2 PMI 加權共現網絡

**共現單位：以「天」為基礎**

PTT 旅遊貼文常在開頭以一句話列出整趟旅程所有目的地（如「這次去了京都、大阪、北海道...」），若以全文為共現單位，會將不屬於同一天的景點建立連結，造成高估。為此以**分日段落**作為共現單位，只計算同一天內的景點對：

```python
day_pattern = re.compile(r'(Day\s*\d+|第[一二三四五六七八九十百]+天|D\d+)', re.IGNORECASE)
segments = re.split(day_pattern, post_text)
# 僅對同一 segment 內的景點建立共現對
```

無分日結構的貼文退回全文共現，並在研究限制中說明。

**PMI 邊權重**，修正高頻景點對低頻景點的主導效應：

```
PMI(A, B) = log[ P(A,B) / (P(A) × P(B)) ]
```

**雜訊過濾**：移除共現次數 < 3 或 PMI ≤ 0 的邊，孤立節點保留於景點資料庫但不納入網絡。

### 4.3 Louvain 社群偵測（對應 RQ1）

以 Modularity Q 最大化為目標，從共現網絡自動找出行程群集：

```
Q = Σ [ (邊在群集內的比例) − (隨機圖中的預期比例) ]
```

Q ≥ 0.3 為群集結構顯著的標準。若初始資料抓取後 Q 值低於門檻（資料過於稀疏），備案為縮小分析範圍至**關東／關西**兩大熱門區域重新執行，或將低頻景點依「市町村」層級適度聚合後再建圖。群集命名取群集內 Degree Centrality 最高的前 3 個景點，結合地理位置與景點類型人工歸納標籤。

預期群集範例（待實際資料驗證）：

| 群集 | 核心景點（示意） | 名稱 |
|------|---------------|------|
| C1 | 伏見稻荷、清水寺、金閣寺 | 京都文化圈 |
| C2 | 美瑛、富良野、旭山動物園 | 北海道自然圈 |
| C3 | 屋久島、霧島、開聞岳 | 九州自然圈 |
| C4 | 天龍寺、嵐山竹林、苔寺 | 京都嵐山圈 |
| C5 | 春日大社、東大寺、若草山 | 奈良文化圈 |

**網絡指標與商業意義**

| 指標 | 定義 | 對平台的意義 |
|------|------|------------|
| Degree Centrality | 景點連結數量（正規化） | 群集核心景點，適合作為行程產品主打賣點 |
| Betweenness Centrality | 作為最短路徑中間節點的頻率 | 跨群集樞紐景點，適合設計跨區多日行程 |
| Clustering Coefficient | 鄰居之間互相連結的比例 | 高分代表緊密子群，適合深度旅遊產品 |

### 4.4 情感分析

針對每個景點，擷取前後 ±50 字的語境文字，以多語言 DistilBERT 模型進行情感分類，取正面機率值（0–1）作為景點情感分數：

```python
from transformers import pipeline

sentiment_pipe = pipeline(
    "sentiment-analysis",
    model="lxyuan/distilbert-base-multilingual-cased-sentiments-student",
    top_k=None
)

def get_sentiment_score(context_text: str) -> float:
    result = sentiment_pipe(context_text[:512])
    label_map = {r["label"]: r["score"] for r in result[0]}
    return label_map.get("positive", 0.0)
```

選用此模型而非 SnowNLP 的原因：SnowNLP 基於簡體中文豆瓣評論訓練，對繁體中文旅遊文的口語語氣識別有限；`lxyuan/distilbert` 在多語言評論資料上訓練，繁中三分類表現穩定。若評估準確率不足，可改用 `cardiffnlp/twitter-xlm-roberta-base-sentiment`（社群文體更接近）。

### 4.5 六維體驗側寫（對應 RQ2）

整體情感分數只回答「旅客喜不喜歡」，無法解釋為何高評價景點仍被商業平台忽略。本節對每個景點從六個維度建立體驗側寫，作為 RQ2 分析的量化依據，同時作為推薦工具的加權輸入。

| 維度 | 方向 | 關鍵詞範例 |
|------|------|-----------|
| 人潮壓力 | 越高越不利 | 排隊、人山人海、人擠人、等很久 / 人很少、清靜 |
| 交通可及性 | 越高越有利 | 步行即達、交通方便、出站即到 / 需要開車、偏遠、很難找 |
| 季節限制 | 越高越不利 | 花季、楓葉、期間限定、只有夏天、冬季才有 |
| 打卡價值 | 越高越有利 | 超好拍、IG、網美、絕景、好拍 |
| CP 值感知 | 越高越有利 | 免費、CP值高、值得、超值 / 有點貴、不值得 |
| 規劃難度 | 越高越不利 | 需要預約、搶票、限流、一票難求 |

```python
dimension_keywords = {
    'crowd':         {'high': ['排隊','人山人海','人擠人','等很久'],     'low': ['人很少','清靜','不擁擠']},
    'accessibility': {'easy': ['步行即達','交通方便','出站即到'],        'hard': ['需要開車','偏遠','交通不便']},
    'seasonal':      {'limited': ['花季','楓葉','期間限定','只有夏天']},
    'photo':         {'high': ['超好拍','IG','網美','絕景']},
    'value':         {'high': ['免費','CP值高','值得'],                  'low': ['有點貴','不值得']},
    'planning':      {'hard': ['需要預約','搶票','限流','一票難求']}
}

def extract_dimensions(spot_contexts: list[str], context_sentiments: list[float]) -> dict:
    """
    context_sentiments: 各語境文字對應的情感分數（由 4.4 節模型輸出）
    關鍵詞命中時以情感分數加權，避免「排隊很值得」這類正向框架的負向詞彙
    被誤判為體驗障礙（命中詞在高情感語境中，壓力分數打六折）
    """
    n = len(spot_contexts)
    scores = {}
    for dim, kw_dict in dimension_keywords.items():
        weighted_pos, weighted_neg = 0.0, 0.0
        for text, sent in zip(spot_contexts, context_sentiments):
            pos_hit = any(kw in text for kw in kw_dict.get('high', kw_dict.get('easy', kw_dict.get('limited', kw_dict.get('hard', [])))))
            neg_hit = any(kw in text for kw in kw_dict.get('low', kw_dict.get('hard', [])))
            sentiment_weight = 1.0 - 0.4 * sent  # 情感越正向，負向維度命中折扣越大
            if pos_hit:
                weighted_pos += 1.0
            if neg_hit:
                weighted_neg += sentiment_weight
        scores[dim] = (weighted_pos - weighted_neg) / n if n > 0 else 0
    return scores
```

**RQ2 統計方法**：以隱藏版景點（4.6 節定義）與非隱藏版景點為兩組，對六個維度分數各自執行 Mann-Whitney U test（無常態分布假設），識別哪些維度在兩組間有顯著差異（p < 0.05）。

### 4.6 隱藏版景點指數（對應 RQ3）

**定義**：在同一行程群集中，情感分數 ≥ 0.65 且出現頻率低於群集第 25 百分位數（Q1）的景點。

```python
threshold = cluster_freq.quantile(0.25)   # 動態門檻，依各群集頻率分布決定
candidates = spots[
    (spots['cluster_freq'] <= threshold) &
    (spots['sentiment'] >= 0.65)
]
hidden_score = sentiment × (1 / log(cluster_freq + 1))
```

Q1 動態門檻的設計理由：不同群集的貼文量差距懸殊，固定絕對門檻會造成跨群集比較失準。Q1 確保每個群集約 25% 的景點進入候選池，再取 top-5 輸出。

**商業曝光驗證**：對候選景點以名稱搜尋 KKday，以**雙層指標**衡量商業曝光程度：

- **主指標（二元）**：景點名稱是否出現於任何產品標題（旅客選購時主要看標題，埋在內文的景點曝光影響有限）
- **輔助指標（連續）**：KKday 搜尋結果筆數，≤ 3 筆可進一步佐證商業缺口的顯著性

```python
def kkday_exposure(spot_name):
    results = scrape_kkday_search(spot_name)
    in_title = any(spot_name in p['title'] for p in results)
    result_count = len(results)
    return {'in_title': in_title, 'result_count': result_count}
```

景點同時滿足「未出現於任何產品標題」且「搜尋結果 ≤ 3 筆」，才認定為高確信度的商業缺口景點。

### 4.7 行程缺口偵測工具（B2B Demo）

基於前述所有分析結果，建立供旅遊平台使用的行程缺口偵測工具。輸入現有行程景點清單，輸出社群認可但尚未納入的潛力景點，附社群數據佐證。工具只回答「缺什麼」，細部排程由平台自行決定。

**運作流程**

```
輸入：現有行程景點清單（如：清水寺、伏見稻荷、金閣寺）
    ↓
Step 1：判斷行程所屬群集
    → 若 ≥ 70% 景點同屬一群集：以該群集為主群集（單群集行程）
    → 若景點分散於多個群集：拆分為各子群集分別推薦，輸出時標記「分區推薦」
    ↓
Step 2【硬過濾】：在主群集內篩選候選景點
    條件：同群集 ＋ 不在現有行程中 ＋ 情感分數 ≥ 0.65 ＋ 距現有任一景點 ≤ 50km
    ↓
Step 3【軟排序】：計算多維推薦分數
    基礎分 = 提及次數 × 情感分數 × (1 + 與現有景點的平均 PMI)
    體驗調整 = (1 − α×人潮) × (1 + β×打卡) × (1 + γ×CP值) × (1 − δ×季節) × (1 − ε×規劃難度)
    最終分數 = 基礎分 × 體驗調整
    （各維度權重預設相等，demo 介面允許使用者依偏好調整）
    ↓
Step 4：排序輸出 top-5，每個景點附社群數據佐證
```

**多群集行程說明**：跨群集輸入的景點（如京都＋北海道）在地理上本就不共現，要求推薦景點對整個輸入清單都有高 PMI 不合理。拆分後各子群集獨立執行 Step 2–4，PMI 計算限同群集景點，避免跨地理區域的分數稀釋。

**地理距離過濾實作**：分日段落共現已保證同一天共現的景點地理上可達，但部分無分日結構的貼文退回全文共現，距離過濾作為安全網。座標直接取自 WikiData，以 Haversine 公式計算：

```python
from math import radians, sin, cos, sqrt, atan2

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = radians(lat2-lat1), radians(lon2-lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def is_within_range(candidate, existing_spots, max_km=50):
    return any(haversine(*coords[candidate], *coords[e]) <= max_km
               for e in existing_spots if e in coords and candidate in coords)
```

**佐證說明格式**

> 「哲學之道：在 PTT Japan 板上，與清水寺同篇出現的貼文中有 68% 也提及哲學之道，平均情感分數 0.81，在京都文化圈群集內社群推薦強度排名第 3，但景點名稱未出現於 KKday 任何產品標題。」

**使用範例：KKday 京都文化圈行程優化**

輸入：伏見稻荷大社、清水寺、金閣寺、嵐山竹林 → 判定主群集為「京都文化圈（C1）」

| 排名 | 推薦景點 | 情感分數 | 社群佐證摘要 | 出現於 KKday 產品標題 |
|------|---------|---------|------------|-------------------|
| 1 | 哲學之道 | 0.84 | 與清水寺同篇貼文中 71% 提及；「春天根本神仙景色」 | 否 ✗ |
| 2 | 南禅寺 | 0.81 | 與金閣寺同篇貼文中 58% 提及；「水路閣很有感」 | 否 ✗ |
| 3 | 貴船神社 | 0.79 | 頻率低於 Q1（隱藏版）；「人少、氣氛好、值得特地跑」 | 否 ✗ |
| 4 | 大原三千院 | 0.77 | 與嵐山同篇貼文中 44% 提及；「想逃離人潮一定要去」 | 否 ✗ |
| 5 | 二条城 | 0.72 | 群集代表景點，平均 PMI 0.31 | 是 ✓ |

此工具直接查詢預先計算好的 PMI 矩陣與群集資料，不需額外模型訓練，以 Streamlit 建立簡易介面供 demo 展示。

---

## 五、驗證計畫

| 驗證項目 | 方法 | 成功標準 |
|---------|------|---------|
| NER 準確率 | 人工標記 200 筆貼文為 ground truth | F1 ≥ 0.8 |
| 情感分析準確率 | 人工標記 200 筆景點語境文字 | 準確率 ≥ 75% |
| 維度關鍵詞效度 | 人工抽查各維度各 30 筆標記結果 | 各維度準確率 ≥ 80% |
| 社群偵測品質 | Modularity Q；人工評估群集語意合理性 | Q ≥ 0.3；人工通過率 ≥ 80% |
| 隱藏版景點商業曝光 | 前 20 名景點搜尋 KKday：(1) 是否出現於產品標題 (2) 搜尋結果筆數 | ≥ 70% 確認未出現於標題；其中 ≥ 50% 搜尋結果 ≤ 3 筆 |
| RQ2 維度差異 | Mann-Whitney U test（隱藏版 vs 非隱藏版） | ≥ 2 個維度 p < 0.05 |

---

## 六、預期結果

### 6.1 方法論貢獻

- 提出結合共現網絡、情感分析與六維體驗側寫的旅遊景點多維評估框架，可推廣至其他目的地或平台
- 以動態 Q1 門檻修正跨群集頻率比較失準的問題，建立可複用的隱藏版景點識別流程

### 6.2 實證發現

- **行程群集**：預期歸納出 8–12 個地理或主題一致的群集，部分景點具高 Betweenness Centrality 作為跨群集樞紐
- **體驗側寫差異**：預期隱藏版景點在「交通可及性」偏低、「季節限制」偏高上與非隱藏版有顯著差異，顯示商業平台傾向迴避難以全年標準化的景點；「打卡價值」預期差異不顯著
- **商業缺口驗證**：預期各群集存在 3–5 個高評價但完全未出現於 KKday 產品標題的景點

### 6.3 平台決策依據

**① 選品缺口清單（對應 RQ3）**：各群集隱藏版景點排行告訴平台「哪些景點社群評價高但無標題曝光」，可作為產品開發的優先評估名單。

**② 缺口成因分析（對應 RQ2）**：六維側寫揭示景點被忽略的原因——交通偏遠或強季節性的景點難以標準化；規劃難度高的景點需要平台提供代訂服務才有商業可行性。讓選品決策從「有無社群口碑」細化為「哪種類型的缺口值得投資」。

**③ 行程產品設計（對應 RQ1）**：群集結構揭示旅客真實的景點搭配邏輯。Betweenness Centrality 高的樞紐景點適合設計多區串聯行程，Clustering Coefficient 高的景點適合深度小眾旅遊產品。

### 6.4 系統產出

- 日本景點共現網絡互動視覺化圖（含群集著色，Pyvis）
- 各群集代表景點與隱藏版景點清單
- 隱藏版 vs 非隱藏版景點六維雷達圖比較（含 Mann-Whitney U 結果）
- 行程缺口偵測工具（Streamlit demo，供 B2B 展示）

---

## 七、技術元件

| 元件 | 技術選擇 |
|------|---------|
| 爬蟲 | Python + requests |
| 斷詞與 NER | CKIP Tagger（中研院） |
| 圖分析 | NetworkX |
| 社群偵測 | python-louvain |
| 視覺化 | Pyvis（互動式）/ Gephi（靜態） |
| 情感分析 | transformers（lxyuan/distilbert-base-multilingual-cased-sentiments-student） |
| 景點座標 | WikiData SPARQL（內含座標，無需另行 Geocoding） |
| 資料庫 | SQLite |
| 前端介面 | Streamlit（B2B demo） |

---

## 八、研究限制

- **用戶代表性**：PTT Japan 板以台灣大學生與上班族為主，分析結果未必適用於其他年齡層或國籍旅客
- **開頭總覽的共現高估**：部分貼文開頭以一句話羅列整趟旅程目的地，即使採用分日段落，無分日結構的貼文仍需退回全文共現；另有部分貼文雖有分日結構，但開頭總覽本身位於第一天段落內。PMI 可部分修正，但無法完全消除系統性偏差
- **關鍵詞字典覆蓋率**：六維體驗側寫以關鍵詞比對為基礎，可能遺漏無關鍵詞的隱性表達（如以描述性語句表達擁擠感而不直接使用「排隊」等詞）。未來可考慮以少量標注資料 fine-tune 分類器取代純關鍵詞比對
- **Louvain 不穩定性**：每次執行結果略有不同，需固定 random seed 並多次執行取最佳 Q 值
- **景點白名單維護**：WikiData 資料有更新延遲，新興景點可能遺漏，需人工補充
- **PTT 文章保存期限**：PTT 文章可能因版主刪文或文章過期而遺失，爬取後應立即本地儲存；部分早期文章可能已不存在，影響長時間序列分析的完整性

---

## 九、初步工作時程

| 週次 | 工作項目 |
|------|---------|
| 第 1 週 | PTT Japan 板爬蟲建立、資料收集 |
| 第 2 週 | 資料清洗；WikiData 查詢＋文化廳爬蟲，建立景點白名單 |
| 第 3 週 | NER 地名擷取、原始共現矩陣建立（分日共現） |
| 第 4 週 | PMI 計算、雜訊過濾、共現圖建立 |
| 第 5 週 | Louvain 社群偵測、群集命名與驗證（RQ1） |
| 第 6 週 | 情感分析、六維體驗側寫計算（RQ2）、隱藏版景點識別與 KKday 驗證（RQ3） |
| 第 7 週 | 行程缺口偵測工具開發（Streamlit） |
| 第 8 週 | 視覺化、整合測試、報告撰寫 |
