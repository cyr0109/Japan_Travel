"""
PTT Japan 板旅遊景點推薦系統
"""

import sqlite3
import streamlit as st
import pandas as pd
import pydeck as pdk
from collections import Counter

DB_PATH = "japan_travel.db"

CLUSTER_LABELS = {
    6: "富士山圈", 7: "京阪圈", 4: "九州自然圈", 17: "中部日本圈",
    2: "北海道道南圈", 5: "東京周邊圈", 1: "宮島・神戶圈", 3: "東北自然圈",
    25: "瀨戶內海島圈", 21: "關東山區溫泉圈", 13: "山陰圈", 0: "伊勢・熊野圈",
}

HIDDEN_SPOTS = {
    "岩倉五条川":   {"gmaps": 263,  "loc": "愛知縣岩倉市", "desc": "1300 株染井吉野，在地賞花第一名", "lat": 35.28, "lon": 136.87},
    "松江神社":     {"gmaps": 428,  "loc": "島根縣松江市", "desc": "松江城旁的低調小神社",           "lat": 35.47, "lon": 133.05},
    "唐津神社":     {"gmaps": 1355, "loc": "佐賀縣唐津市", "desc": "唐津城旁千年古社，在地人才知道", "lat": 33.45, "lon": 129.97},
    "須磨浦山上遊園":{"gmaps": 1005, "loc": "兵庫縣神戶市", "desc": "神戶西側復古遊樂園，家庭推薦",  "lat": 34.64, "lon": 135.08},
    "有樂苑":       {"gmaps": 422,  "loc": "愛知縣犬山市", "desc": "織田有樂齋建造的歷史茶庭",       "lat": 35.38, "lon": 136.94},
    "賀露神社":     {"gmaps": 152,  "loc": "鳥取縣鳥取市", "desc": "在地小神社，附近有海鮮市場",     "lat": 35.52, "lon": 134.23},
    "安樂寺":       {"gmaps": 27,   "loc": "長野縣上田市", "desc": "日本現存唯一八角形三重塔",       "lat": 36.34, "lon": 138.22},
    "鴨ヶ磯展望所": {"gmaps": 168,  "loc": "島根縣大田市", "desc": "偏僻海岸展望台，幾乎無觀光客",   "lat": 35.17, "lon": 132.53},
}


@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT ss.spot, ss.cluster_id, ss.sentiment_score, ss.doc_freq, sc.degree
        FROM spot_sentiment ss
        LEFT JOIN spot_clusters sc ON ss.spot = sc.spot
        WHERE ss.sentiment_score IS NOT NULL
    """, conn)
    conn.close()
    return df


@st.cache_data
def get_all_spot_names():
    """只回傳有進入主流 PMI 群集的景點（排除城市地名、低頻孤立節點）。"""
    conn = sqlite3.connect(DB_PATH)
    names = [r[0] for r in conn.execute("""
        SELECT DISTINCT ss.spot FROM spot_sentiment ss
        JOIN llm_spots_clean lc ON ss.spot = lc.spot
        WHERE ss.cluster_id IN (0,1,2,3,4,5,6,7,13,17,21,25)
          AND ss.sentiment_score IS NOT NULL
        ORDER BY ss.spot
    """).fetchall()]
    conn.close()
    return names


def find_main_cluster(input_spots, df):
    counts = Counter()
    for spot in input_spots:
        row = df[df["spot"] == spot]
        if not row.empty and pd.notna(row.iloc[0]["cluster_id"]):
            counts[int(row.iloc[0]["cluster_id"])] += 1
    return counts.most_common(1)[0][0] if counts else None


def recommend(input_spots, cluster_id, df, top_n=8):
    return (
        df[(df["cluster_id"] == cluster_id)
           & (~df["spot"].isin(input_spots))
           & (df["sentiment_score"] >= 0.5)]
        .sort_values("sentiment_score", ascending=False)
        .head(top_n)
    )


# ── 頁面設定 ────────────────────────────────────────────────────────────
st.set_page_config(page_title="PTT 日本景點推薦", page_icon="🗾", layout="wide")
st.title("🗾 PTT 日本旅遊景點推薦")
st.caption("基於 PTT Japan 板 20,487 篇文章的社群口碑分析 ｜ Social Media Analytics 2026")

spots_df = load_data()
all_names = get_all_spot_names()

# ── 頂層分頁 ─────────────────────────────────────────────────────────────
tab_rec, tab_hidden = st.tabs(["📍 景點推薦", "🔍 隱藏景點"])

# ═══════════════════════════════════════════════════════════════════
# Tab 1：景點推薦
# ═══════════════════════════════════════════════════════════════════
with tab_rec:
    col_input, col_stats = st.columns([3, 1])

    with col_input:
        st.subheader("輸入您的行程景點")
        selected = st.multiselect(
            "選擇已規劃的景點（可多選，輸入中文搜尋）",
            options=all_names,
            placeholder="例如：富士山、河口湖、嵐山…",
        )

    with col_stats:
        st.subheader("資料規模")
        st.metric("PTT 文章", "20,487 篇")
        st.metric("景點白名單", "544 個")
        st.metric("Louvain 群集", "21 個（Q=0.8817）")

    st.markdown("---")

    if not selected:
        st.info("請在上方選擇您規劃中的景點，系統會推薦同行程圈的高評價景點。")
    else:
        cluster_id = find_main_cluster(selected, spots_df)
        if cluster_id is not None:
            label = CLUSTER_LABELS.get(cluster_id, f"群集 C{cluster_id}")
            cluster_size = int((spots_df["cluster_id"] == cluster_id).sum())
            st.subheader(f"📍 行程所屬群集：{label}")
            st.caption(f"此群集共 {cluster_size} 個景點，以下為同群集社群評價最高的推薦景點")

            recs = recommend(selected, cluster_id, spots_df)
            if not recs.empty:
                cols = st.columns(min(4, len(recs)))
                for i, (_, row) in enumerate(recs.iterrows()):
                    spot = row["spot"]
                    is_hidden = spot in HIDDEN_SPOTS
                    with cols[i % 4]:
                        if is_hidden:
                            info = HIDDEN_SPOTS[spot]
                            st.markdown(f"""
                            <div style="border:2px solid #e74c3c;border-radius:10px;padding:14px;background:#fff5f5;margin-bottom:8px;color:#222">
                            <b style="color:#c0392b">🔍 {spot}</b><br>
                            <span style="color:#e74c3c;font-size:11px">⭐ 隱藏景點</span><br>
                            <span style="font-size:12px;color:#555">{info['desc']}</span><br><br>
                            <span style="color:#333">情感：<b>{row['sentiment_score']:.3f}</b>　PTT：{int(row['doc_freq'])} 篇</span>
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
                            <div style="border:1px solid #ddd;border-radius:10px;padding:14px;margin-bottom:8px;color:#222">
                            <b style="color:#222">{spot}</b><br><br>
                            <span style="color:#333">情感：<b>{row['sentiment_score']:.3f}</b>　PTT：{int(row['doc_freq'])} 篇</span>
                            </div>
                            """, unsafe_allow_html=True)
            else:
                st.info("此群集內無額外推薦景點")
        else:
            st.warning("輸入景點不在本研究的主流行程群集中，無法判斷所屬群集。")

# ═══════════════════════════════════════════════════════════════════
# Tab 2：隱藏景點
# ═══════════════════════════════════════════════════════════════════
with tab_hidden:
    st.subheader("社群口碑高、商業曝光極低的 8 個景點")
    st.caption(
        "篩選條件：PTT 情感分數 > 0.6　｜　KKday 無商業曝光　｜　Google Maps 評論數 < 1,500 則"
    )

    # ── 地圖 ──────────────────────────────────────────────────────────
    map_data = pd.DataFrame([
        {"spot": s, "lat": info["lat"], "lon": info["lon"],
         "gmaps": info["gmaps"], "sent": spots_df[spots_df["spot"] == s]["sentiment_score"].values[0]
         if len(spots_df[spots_df["spot"] == s]) > 0 else 0}
        for s, info in HIDDEN_SPOTS.items()
    ])

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=map_data,
        get_position="[lon, lat]",
        get_radius=25000,
        get_fill_color=[231, 76, 60, 200],
        pickable=True,
    )
    text_layer = pdk.Layer(
        "TextLayer",
        data=map_data,
        get_position="[lon, lat]",
        get_text="spot",
        get_size=14,
        get_color=[50, 50, 50],
        get_anchor_x="'middle'",
        get_pixel_offset=[0, -30],
        pickable=False,
    )
    view = pdk.ViewState(latitude=35.5, longitude=136.0, zoom=5.2, pitch=0)
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer, text_layer],
            initial_view_state=view,
            tooltip={"text": "{spot}\nGMaps：{gmaps} 則評論\nPTT sentiment：{sent:.3f}"},
            map_style="light",
            height=420,
        ),
        use_container_width=True,
    )

    # ── 卡片清單 ──────────────────────────────────────────────────────
    st.markdown("#### 景點詳情")
    sorted_spots = sorted(
        HIDDEN_SPOTS.items(),
        key=lambda x: spots_df[spots_df["spot"] == x[0]]["sentiment_score"].values[0]
        if len(spots_df[spots_df["spot"] == x[0]]) > 0 else 0,
        reverse=True,
    )
    cols = st.columns(2)
    for i, (spot, info) in enumerate(sorted_spots):
        row = spots_df[spots_df["spot"] == spot]
        sent = float(row["sentiment_score"].values[0]) if len(row) > 0 else 0.0
        freq = int(row["doc_freq"].values[0]) if len(row) > 0 else 0
        with cols[i % 2]:
            st.markdown(f"""
            <div style="border:1.5px solid #e74c3c;border-radius:10px;padding:16px;margin-bottom:12px;background:#fff8f8;color:#222">
            <b style="font-size:15px;color:#c0392b">🔍 {spot}</b>
            <span style="float:right;color:#888;font-size:12px">{info['loc']}</span><br>
            <span style="color:#444;font-size:13px">{info['desc']}</span><br><br>
            <span style="font-size:12px;color:#333">
            PTT 情感分數：<b>{sent:.3f}</b>　｜　PTT 篇數：{freq}　｜　GMaps：{info['gmaps']:,} 則　｜　KKday：❌
            </span>
            </div>
            """, unsafe_allow_html=True)

    st.info(
        "💡 這 8 個景點的 PTT 平均情感分數 0.738，遠高於語料整體均值（0.529），"
        "但 Google Maps 平均評論數僅 470 則——品質不輸主流，卻幾乎不存在於大眾旅遊視野中。"
    )
