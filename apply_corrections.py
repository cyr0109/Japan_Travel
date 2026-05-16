"""Apply corrections to review_spots.csv and print a change report."""
import csv, shutil

INPUT  = "review_spots.csv"
OUTPUT = "review_spots.csv"
BACKUP = "review_spots_backup.csv"

# ── 1→0: not a tourist spot ─────────────────────────────────────────────────
TO_ZERO = {
    # prefecture / city (too generic)
    "鹿兒島","鹿児島","富山","德島","福島","仙台","姬路","神戶","北九州",
    "岡山","松山","松江","福山","津山","千葉","福知山","和歌山",
    # region (too generic)
    "北陸","東亞","西九州","道東","道東三湖","關西廣域","北歐",
    "九州島","四國島","北半島","南島","北山","東京廣域",
    # theme parks (excluded - these are enclosed facilities, not open spots)
    "迪士尼","迪士尼海洋","迪士尼陸地","太空山",
    # non-Japan geography
    "歐洲","亞洲","東南亞","巴爾幹半島","峇里島","西伯利亞","堪察加半島",
    "阿爾卑斯山","阿爾卑斯山脈","地中海","南美洲","北美","俄波羅的海",
    "北歐","西洋","歐美","歐陸","東洋","泰山","上海灘",
    # Taiwan
    "陽明山","日月潭","台北盆地","合歡山","阿里山","花東縱谷",
    "愛河","澎湖","龜山島","東北角","七星山","玉山","青島",
    "口湖","淡水河",
    # seas / bays that are not specifically touristic
    "日本海","瀨戶內海","太平洋","東海","東京灣","鄂霍次克海",
    "南海","伊勢灣","博多灣","博多港","青森港",
    # generic geographic terms
    "半島","離島","群島","海峽","東海岸","西岸","南岸","北半島",
    "三角洲","三湖","二湖","四湖","盆地","東南","東南角",
    "西北","沙洲","石板路","西海岸","東三湖","雲峽",
    # disputed / politically sensitive
    "竹島","北方四島","國後島","庫頁島",
    # fictional / mythological / not places
    "銀河","北極","北極星","南極","地球","三途川","耀西","秋名山",
    "神秘島","獨木舟","花崗岩","百名山","綠洲","北極熊",
    # malformed NER output
    "士山","夫里島","富士山山","爺湖","琶湖","鼻溪","山陽山","道湖",
    "富士山河口湖",
    # generic nouns
    "半山腰","展望台","海峽","白沙灘","大馬路","護城河",
    "東亞","西九州","南亞","東南",
    # others
    "赤壁","近江","長島","米原","沖繩島","沖繩本島","琉球群島",
    "日本列島","羽田","土庄港","極南","冰河","北山",
    "關西廣域","南美洲","福知山",
}

# ── 0→1: was auto-rejected but IS a tourist spot ────────────────────────────
TO_ONE = {
    "倉敷美觀地區",   # famous historic district
}

shutil.copy(INPUT, BACKUP)

rows = []
with open(INPUT, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        rows.append(row)

changes = []
for row in rows:
    entity = row["entity"]
    old = row["add_to_whitelist"]
    if entity in TO_ZERO and old != "0":
        row["add_to_whitelist"] = "0"
        changes.append(("1→0", entity, row["posts"]))
    elif entity in TO_ONE and old != "1":
        row["add_to_whitelist"] = "1"
        changes.append(("0→1", entity, row["posts"]))

with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

# report
print(f"\n{'='*55}")
print(f"總計修改 {len(changes)} 筆")
print(f"{'='*55}")

zero_changes = [(e,p) for t,e,p in changes if t=="1→0"]
one_changes  = [(e,p) for t,e,p in changes if t=="0→1"]

print(f"\n■ 改為 0（排除）{len(zero_changes)} 筆：")
categories = {
    "縣市/地區（太泛化）": ["鹿兒島","鹿児島","富山","德島","福島","仙台","姬路","神戶","北九州","岡山","松山","松江","福山","津山","千葉","福知山","和歌山","北陸","東亞","西九州","道東","道東三湖","關西廣域","北歐","九州島","四國島","北半島","南島","北山","東京廣域","近江"],
    "購物/娛樂商圈（研究範圍排除）": ["秋葉原","心齋橋","中洲","豊洲","豐洲","梅田","代官山","澀谷","渋谷","東武","西武","淺草橋","神田","八重洲"],
    "主題樂園（研究範圍排除）": ["迪士尼","迪士尼海洋","迪士尼陸地","太空山"],
    "非日本地理": ["歐洲","亞洲","東南亞","巴爾幹半島","峇里島","西伯利亞","堪察加半島","阿爾卑斯山","阿爾卑斯山脈","地中海","南美洲","北美","俄波羅的海","西洋","歐美","歐陸","東洋","泰山","上海灘"],
    "台灣景點": ["陽明山","日月潭","台北盆地","合歡山","阿里山","花東縱谷","愛河","澎湖","龜山島","東北角","七星山","玉山","青島","口湖","淡水河"],
    "海域/海灣（非景點）": ["日本海","瀨戶內海","太平洋","東海","東京灣","鄂霍次克海","南海","伊勢灣","博多灣","博多港","青森港"],
    "泛化地理名詞": ["半島","離島","群島","海峽","東海岸","西岸","南岸","三角洲","三湖","二湖","四湖","盆地","東南","沙洲","石板路","西海岸","東三湖","雲峽","竹島","北方四島","國後島","庫頁島"],
    "虛構/非地名": ["銀河","北極","北極星","南極","地球","三途川","耀西","秋名山","神秘島","獨木舟","花崗岩","百名山","綠洲","北極熊","半山腰","展望台","白沙灘","大馬路","護城河"],
    "NER截斷/錯誤": ["士山","夫里島","富士山山","爺湖","琶湖","鼻溪","山陽山","道湖","富士山河口湖"],
}
printed = set()
for cat, ents in categories.items():
    matched = [(e,p) for e,p in zero_changes if e in ents]
    if matched:
        print(f"\n  【{cat}】")
        for e, p in matched:
            print(f"    {e}（{p} posts）")
            printed.add(e)
other = [(e,p) for e,p in zero_changes if e not in printed]
if other:
    print(f"\n  【其他】")
    for e,p in other:
        print(f"    {e}（{p} posts）")

if one_changes:
    print(f"\n■ 改為 1（加入）{len(one_changes)} 筆：")
    for e,p in one_changes:
        print(f"    {e}（{p} posts）")

remaining_spots = sum(1 for r in rows if r["add_to_whitelist"]=="1")
print(f"\n修正後剩餘景點候選：{remaining_spots} 個")
print(f"備份已存至 {BACKUP}")
