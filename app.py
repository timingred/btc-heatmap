import streamlit as st
import streamlit.components.v1 as components
import json, requests, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# 1. 페이지 설정 및 초기화
st.set_page_config(page_title="TIMINGBIT LIQUIDATION INTELLIGENCE", layout="wide")

if 'period' not in st.session_state: st.session_state.period = "24H"

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

# 2. 전역 스타일 (가독성 및 티커 화이트 고정)
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');
    :root { 
        --bg: #05050a; --card: #0e0e1a; --border: #1e1e30; 
        --green: #00ffa3; --red: #ff3e3e; --gold: #ffcc00; 
        --cyan: #00f2ff; --orange: #ff8c00; --dim: #6b6b7b; 
    }
    .stApp {background-color: var(--bg); color: #e1e1e6;}
    .block-container {padding: 1rem 2rem !important; max-width: 100%; font-family: 'JetBrains Mono', sans-serif !important;}
    [data-testid="stHeader"] {display: none;}
    
    /* 티커 버튼 화이트 고정 및 크기 확대 */
    .stRadio div[role="radiogroup"] { flex-direction: row !important; gap: 15px; }
    .stRadio div[role="radiogroup"] label { 
        background: #1a1a2e !important; border: 2px solid var(--border) !important; padding: 12px 50px !important; border-radius: 8px !important; 
        color: #FFFFFF !important; font-size: 22px !important; font-weight: 900 !important; cursor: pointer; transition: 0.2s;
    }
    .stRadio div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child { display: none; }
    div[data-testid="stMarkdownContainer"] + div .stRadio div[role="radiogroup"] label[data-checked="true"] {
        border-color: var(--green) !important; background: rgba(0, 255, 163, 0.2) !important;
        box-shadow: 0 0 15px rgba(0, 255, 163, 0.4);
    }
    </style>
    """, unsafe_allow_html=True)

# 3. 데이터 엔진
def safe_api_call(url, is_post=True, payload=None):
    try:
        if is_post: res = requests.post(url, json=payload, timeout=8)
        else: res = requests.get(url, timeout=8)
        return res.json() if res.status_code == 200 else None
    except: return None

@st.cache_data(ttl=12)
def fetch_basic_data(coin, period_label):
    # 가격
    mids = safe_api_call("https://api.hyperliquid.xyz/info", payload={"type": "allMids"})
    px = float(mids[coin]) if mids and coin in mids else 0
    
    # 리더보드 고래 데이터 (인원 최적화)
    cfg_map = {"24H": 150, "48H": 200, "3D": 250, "1W": 300, "2W": 400, "1M": 500, "ALL": 800}
    user_count = cfg_map.get(period_label, 150)
    lb = safe_api_call(f"https://stats-data.hyperliquid.xyz/Mainnet/leaderboard?window=day", is_post=False)
    
    hl_pos = []
    if lb:
        addrs = [r["ethAddress"] for r in lb.get("leaderboardRows", [])[:user_count] if r.get("ethAddress")]
        def fetch_hl(a):
            d = safe_api_call("https://api.hyperliquid.xyz/info", payload={"type": "clearinghouseState", "user": a})
            if d and "assetPositions" in d:
                for ap in d["assetPositions"]:
                    p = ap.get("position")
                    if p and coin in str(p.get("coin", "")).upper():
                        return {"liqPx": float(p.get("liquidationPx") or 0), "posVal": float(p.get("positionValue") or 0), "isLong": float(p.get("szi") or 0) > 0, "user": a[:6]}
            return None
        with ThreadPoolExecutor(max_workers=40) as ex:
            hl_pos = [r for r in list(ex.map(fetch_hl, addrs)) if r]
            
    return {"price": px, "positions": hl_pos}

# 4. 메인 실행
h1, h2 = st.columns([2.5, 1])
with h1: st.markdown("<h1 style='color:var(--green); margin:0; font-weight:900;'>🐋 TIMINGBIT LIQUIDATION INTELLIGENCE</h1>", unsafe_allow_html=True)
with h2: coin = st.radio("COIN", ["BTC", "ETH"], horizontal=True, label_visibility="collapsed")

data = fetch_basic_data(coin, st.session_state.period)

if data:
    px, all_pos = data['price'], data['positions']

    # 필터 컨트롤러
    p_list = ["24H", "48H", "3D", "1W", "2W", "1M", "ALL"]
    c1, c2, c3, c4 = st.columns(4)
    with c1: 
        selected_p = st.selectbox("분석 그룹 (기간)", p_list, index=p_list.index(st.session_state.period))
        if selected_p != st.session_state.period:
            st.session_state.period = selected_p
            st.rerun()
    with c2: range_p = st.selectbox("표시 범위 %", [1, 2, 5, 10, 15, 20, 30, 50], index=4)
    with c3: step_s = st.selectbox("사다리 정밀도 $", [1, 5, 10, 50, 100, 200], index=2)
    with c4: min_val = st.number_input("최소 물량 필터 ($)", value=0)

    # 사다리 연산
    lo, hi = px * (1 - range_p/100), px * (1 + range_p/100)
    ladder = {}
    for p in all_pos:
        liq = p['liqPx']
        if lo <= liq <= hi:
            b = round(liq / step_s) * step_s
            if b not in ladder: ladder[b] = {"L": 0, "S": 0}
            if p['isLong']: ladder[b]["L"] += p['posVal']
            else: ladder[b]["S"] += p['posVal']

    # 시각화 데이터
    max_v = max([v["L"] + v["S"] for v in ladder.values()] + [1])
    max_d = max([abs(v["S"] - v["L"]) for v in ladder.values()] + [1])
    whales = sorted(all_pos, key=lambda x: x['posVal'], reverse=True)[:15]
    for w in whales:
        # 평단가 추정 (SMC 기준 5배 레버리지 가정)
        w['ent'] = w['liqPx'] / 0.8 if w['isLong'] else w['liqPx'] / 1.2
        w['isP'] = (px > w['ent']) if w['isLong'] else (px < w['ent'])

    payload = json.dumps({"price": px, "map": ladder, "whales": whales, "maxV": max_v, "maxD": max_d, "coin": coin, "minV": min_val, "tL": sum(p['posVal'] for p in all_pos if p['isLong']), "tS": sum(p['posVal'] for p in all_pos if not p['isLong'])})

    # HTML 렌더링 (사다리 맵)
    html_code = f"""
    <!DOCTYPE html><html><head><link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@600;800&display=swap" rel="stylesheet"><style>
    :root{{--bg:#05050a;--card:#0e0e1a;--ln:#1e1e30;--g:#00ffa3;--r:#ff3e3e;--gold:#ffcc00;--cyan:#00f2ff;--orange:#ff8c00;--dim:#6b6b7b;}}
    body{{background:var(--bg); color:#e1e1e6; font-family:'JetBrains Mono', monospace; margin:0; padding:10px; overflow-x:hidden;}}
    #wCard{{display:grid; grid-template-columns: repeat(5, 1fr); gap:12px; margin-bottom:25px;}}
    .wc{{background:var(--card); border:1px solid var(--ln); padding:15px; border-radius:8px; font-size:14px; position:relative; line-height:1.6;}}
    .pl-tag{{position:absolute; top:12px; right:12px; font-size:9px; font-weight:800; padding:2px 5px; border-radius:4px;}}
    .profit{{background:rgba(0,255,163,0.15); color:var(--g);}} .loss{{background:rgba(255,62,62,0.15); color:var(--r);}}
    #deltaBar{{margin:15px 0; height:50px; background:var(--card); border-radius:8px; display:flex; overflow:hidden; font-size:18px; font-weight:800; border:1px solid var(--ln)}}
    #dL{{background:var(--g); color:#000; display:flex; align-items:center; padding:0 25px;}} #dS{{background:var(--r); color:#000; display:flex; align-items:center; justify-content:flex-end; padding:0 25px;}}
    .row{{display:grid; grid-template-columns: 120px 80px 1.5fr 120px 100px; height:26px; align-items:center; gap:12px; margin-bottom:2px; padding:0 10px;}}
    .px{{text-align:right; font-weight:800; color:#fff; font-size:15px;}}
    .bc{{height:16px; background:#121221; border-radius:2px; position:relative; overflow:hidden;}} .bar{{height:100%; position:absolute;}}
    .curB{{height:60px; background:rgba(255,204,0,0.15); color:var(--gold); display:flex; align-items:center; justify-content:center; font-weight:800; margin:20px 0; border:2px solid rgba(255,204,0,0.5); font-size:24px; border-radius:8px;}}
    </style></head><body><div id="wCard"></div><div id="deltaBar"><div id="dL">LONG</div><div id="dS">SHORT</div></div><div id="main"></div><script>
    const d = {payload}; document.getElementById('wCard').innerHTML = d.whales.map(f => `<div class="wc"><span class="pl-tag ${{f.isP?'profit':'loss'}}">${{f.isP?'PROFIT':'LOSS'}}</span>ID: <b style="color:var(--gold)">${{f.user}}</b> | <span style="color:${{f.isLong?'var(--g)':'var(--r)'}}">${{f.isLong?'L':'S'}}</span><br>SZ: <b>$${{(f.posVal/1e6).toFixed(1)}}M</b><br>LIQ: <b style="color:var(--cyan)">$${{f.liqPx.toLocaleString(undefined, {{maximumFractionDigits:d.coin==='BTC'?0:2}})}}</b></div>`).join('');
    const lPct = (d.tL / (d.tL + d.tS || 1)) * 100; document.getElementById('dL').style.flex = lPct; document.getElementById('dS').style.flex = 100 - lPct; document.getElementById('dL').innerHTML = `L ${{Math.round(lPct)}}%`; document.getElementById('dS').innerHTML = `${{Math.round(100-lPct)}}% S`;
    const prices = Object.keys(d.map).map(Number).sort((a,b)=>b-a); let html = ''; let mid = false; prices.forEach(p => {{ const data = d.map[p]; if(!mid && p <= d.price) {{ html += `<div class="curB">${{d.coin}} MARKET PRICE: $${{d.price.toLocaleString()}}</div>`; mid = true; }} if((data.L + data.S) < d.minV) return; html += `<div class="row"><div class="px">$${{p.toLocaleString(undefined, {{minimumFractionDigits:d.coin==='BTC'?0:1}})}}</div><div class="pct" style="text-align:right; font-size:12px; color:var(--dim);">${{(((p-d.price)/d.price)*100).toFixed(1)}}%</div><div class="bc"><div class="bar" style="width:${{(data.L/d.maxV)*100}}%; background:var(--g); left:0; position:absolute;"></div><div class="bar" style="width:${{(data.S/d.maxV)*100}}%; background:var(--r); right:0; position:absolute;"></div></div><div style="height:12px; background:#1a1a2e; border-radius:2px; position:relative; overflow:hidden;"><div style="height:100%; width:${{(Math.abs(data.S-data.L)/d.maxD)*100}}%; background:${{data.S>=data.L?'var(--cyan)':'var(--orange)'}}; margin-left:${{data.S<data.L?'auto':'0'}}"></div></div><div style="font-size:14px; color:var(--cyan); font-weight:800; text-align:right;">$${{((data.L+data.S)/1e6).toFixed(1)}}M</div></div>`; }});
    document.getElementById('main').innerHTML = html;</script></body></html>
    """
    components.html(html_code, height=1500, scrolling=True)
