import streamlit as st
import streamlit.components.v1 as components
import json, requests, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# 1. 페이지 설정
st.set_page_config(page_title="LIQUIDATION INTELLIGENCE PRO", layout="wide")

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

# 2. 전역 스타일
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');
    :root { 
        --bg: #05050a; --card: #0e0e1a; --border: #1e1e30; 
        --green: #00ffa3; --red: #ff3e3e; --gold: #ffcc00; 
        --cyan: #00f2ff; --orange: #ff8c00; --binance: #F3BA2F; --dim: #6b6b7b; 
    }
    .stApp {background-color: var(--bg); color: #e1e1e6;}
    .block-container {padding: 0.5rem 2rem !important; max-width: 100%;}
    [data-testid="stHeader"] {display: none;}
    footer {display: none;}
    .stRadio div[role="radiogroup"] { flex-direction: row !important; gap: 10px; }
    .stRadio div[role="radiogroup"] label { 
        background: #1a1a2e; border: 1px solid var(--border); padding: 5px 20px !important; border-radius: 4px; color: var(--dim); font-weight: 800; cursor: pointer; transition: 0.3s;
    }
    .stRadio div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child { display: none; }
    .stRadio div[role="radiogroup"] label:hover { border-color: var(--green); }
    </style>
    """, unsafe_allow_html=True)

# 3. 데이터 엔진
def safe_api_call(url, payload=None, is_post=True):
    try:
        if is_post: res = requests.post(url, json=payload, timeout=10)
        else: res = requests.get(url, timeout=10)
        return res.json() if res.status_code == 200 else None
    except: return None

@st.cache_data(ttl=12)
def fetch_data(coin, period):
    mids = safe_api_call("https://api.hyperliquid.xyz/info", {"type": "allMids"})
    px = float(mids[coin]) if mids and coin in mids else 0
    if px == 0: return None
    cfg = {"24H": 100, "48H": 150, "1W": 200, "ALL": 300}.get(period, 100)
    window = "allTime" if period == "ALL" else "day"
    lb = safe_api_call(f"https://stats-data.hyperliquid.xyz/Mainnet/leaderboard?window={window}", is_post=False)
    hl_pos = []
    if lb:
        addrs = [r["ethAddress"] for r in lb.get("leaderboardRows", [])[:cfg] if r.get("ethAddress")]
        def fetch_hl(a):
            d = safe_api_call("https://api.hyperliquid.xyz/info", {"type": "clearinghouseState", "user": a})
            if d and "assetPositions" in d:
                for ap in d["assetPositions"]:
                    p = ap.get("position")
                    if p and coin in str(p.get("coin", "")).upper():
                        return {"liqPx": float(p.get("liquidationPx") or 0), "posVal": float(p.get("positionValue") or 0), "isLong": float(p.get("szi") or 0) > 0, "user": a[:6]}
            return None
        with ThreadPoolExecutor(max_workers=30) as ex:
            hl_pos = [r for r in list(ex.map(fetch_hl, addrs)) if r]
    return {"price": px, "positions": hl_pos}

# 4. 레이아웃
h_col1, h_col2 = st.columns([2, 1])
with h_col1:
    st.markdown(f"<h1 style='color:var(--green); margin:0; font-weight:900;'>🐋 LIQUIDATION INTELLIGENCE PRO</h1>", unsafe_allow_html=True)
with h_col2:
    coin = st.radio("COIN", ["BTC", "ETH", "SOL"], horizontal=True, label_visibility="collapsed")

data = fetch_data(coin, "24H")
if data:
    st.success(f"{coin} 데이터 로드 완료! 현재가: ${data['price']:,}")
    st.write(f"추적 중인 고래 포지션 수: {len(data['positions'])}개")
