import streamlit as st
import streamlit.components.v1 as components
import json, requests, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# 1. 페이지 설정
st.set_page_config(page_title="LIQUIDATION INTELLIGENCE PRO", layout="wide")

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

# 2. 전역 스타일 (자석 강도 디자인 추가)
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');
    :root { 
        --bg: #05050a; --card: #0e0e1a; --border: #1e1e30; 
        --green: #00ffa3; --red: #ff3e3e; --gold: #ffcc00; 
        --cyan: #00f2ff; --orange: #ff8c00; --dim: #6b6b7b; 
    }
    .stApp {background-color: var(--bg); color: #e1e1e6;}
    [data-testid="stHeader"] {display: none;}
    
    /* 자석 강도 카드 디자인 */
    .magnet-card { 
        background: linear-gradient(90deg, rgba(255,140,0,0.1) 0%, rgba(5,5,10,1) 100%);
        border-left: 5px solid var(--orange); padding: 15px; border-radius: 4px; margin: 15px 0;
        display: flex; justify-content: space-between; align-items: center;
    }
    .magnet-val { font-size: 24px; font-weight: 900; color: var(--orange); }
    .status-tag { padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 800; }
    
    .stRadio div[role="radiogroup"] { flex-direction: row !important; gap: 10px; }
    .stRadio div[role="radiogroup"] label { 
        background: #1a1a2e; border: 1px solid var(--border); padding: 5px 20px !important; border-radius: 4px; color: var(--dim); font-weight: 800; cursor: pointer; transition: 0.3s;
    }
    .stRadio div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child { display: none; }
    .stRadio div[role="radiogroup"] label:hover { border-color: var(--green); }
    </style>
    """, unsafe_allow_html=True)

# 3. 데이터 엔진 (잠재 물량 연산 추가)
@st.cache_data(ttl=12)
def fetch_data_v2(coin, period):
    mids = requests.post("https://api.hyperliquid.xyz/info", json={"type": "allMids"}).json()
    px = float(mids[coin]) if mids and coin in mids else 0
    if px == 0: return None
    
    # 하이퍼리퀴드 고래 데이터
    lb = requests.get(f"https://stats-data.hyperliquid.xyz/Mainnet/leaderboard?window=day").json()
    addrs = [r["ethAddress"] for r in lb.get("leaderboardRows", [])[:100] if r.get("ethAddress")]
    
    def fetch_hl(a):
        d = requests.post("https://api.hyperliquid.xyz/info", json={"type": "clearinghouseState", "user": a}).json()
        if d and "assetPositions" in d:
            for ap in d["assetPositions"]:
                p = ap.get("position")
                if p and coin in str(p.get("coin", "")).upper():
                    return {"liqPx": float(p.get("liquidationPx") or 0), "posVal": float(p.get("positionValue") or 0), "isLong": float(p.get("szi") or 0) > 0, "user": a[:6]}
        return None
    
    with ThreadPoolExecutor(max_workers=30) as ex:
        hl_pos = [r for r in list(ex.map(fetch_hl, addrs)) if r]

    # [미래형 데이터] 현재가 1% 이내에 쌓인 잠재 청산 물량
    potential_vol = sum(p['posVal'] for p in hl_pos if px * 0.99 <= p['liqPx'] <= px * 1.01)
    
    # [과거형 데이터] 바이낸스 실제 청산
    bn_res = requests.get(f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={coin}USDT&limit=50")
    actual_liq = sum(float(o['origQty']) * float(o['price']) for o in bn_res.json()) if bn_res.status_code == 200 else 0

    return {"price": px, "positions": hl_pos, "magnet": (potential_vol + actual_liq) / 1e6}

# 4. 레이아웃
h_col1, h_col2 = st.columns([2, 1])
with h_col1:
    st.markdown(f"<h1 style='color:var(--green); margin:0; font-weight:900;'>🐋 LIQUIDATION INTELLIGENCE PRO</h1>", unsafe_allow_html=True)
with h_col2:
    coin = st.radio("COIN", ["BTC", "ETH", "SOL"], horizontal=True, label_visibility="collapsed")

data = fetch_data_v2(coin, "24H")

if data:
    px, magnet_score = data['price'], data['magnet']
    
    # 상태 판별
    status = "STABLE"
    status_color = "#6b6b7b"
    if magnet_score > 5: status, status_color = "WARNING", "#ff8c00"
    if magnet_score > 15: status, status_color = "CRITICAL", "#ff3e3e"

    # 상단 자석 강도 카드 (쓸모 있는 데이터로 교체)
    st.markdown(f"""
        <div class="magnet-card">
            <div>
                <span style="color:var(--dim); font-size:12px;">{coin} 청산 자석 강도 (실시간+잠재)</span><br>
                <span class="status-tag" style="background:{status_color}; color:#000;">{status}</span>
            </div>
            <div class="magnet-val">${magnet_score:.2f}M</div>
        </div>
    """, unsafe_allow_html=True)

    # ... (이후 고래 카드 및 사다리 로직은 동일)
    st.info(f"💡 현재 가격($ {px:,.1f}) 근처 1% 범위 내에 약 ${magnet_score:.1f}M 규모의 청산 지뢰가 매설되어 있습니다.")
