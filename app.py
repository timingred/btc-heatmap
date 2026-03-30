import streamlit as st
import streamlit.components.v1 as components
import json, requests, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# 1. 페이지 설정
st.set_page_config(page_title="TIMINGBIT LIQUIDATION INTELLIGENCE", layout="wide")

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

# 로그 기록 함수
def add_log(msg, log_type="info"):
    colors = {"info": "#6b6b7b", "success": "#00ffa3", "warning": "#ff8c00", "danger": "#ff3e3e"}
    now = get_kst_now().strftime("%H:%M:%S")
    log_entry = f'<div class="log-entry" style="color:{colors.get(log_type, "#6b6b7b")}"><span style="color:#444">[ {now} ]</span> {msg}</div>'
    if 'briefing_history' not in st.session_state:
        st.session_state.briefing_history = []
    st.session_state.briefing_history.insert(0, log_entry)

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
    .block-container {padding: 0.5rem 2rem !important; max-width: 100%; font-family: 'JetBrains Mono', sans-serif !important;}
    [data-testid="stHeader"] {display: none;}
    footer {display: none;}

    /* 코인 선택 버튼 */
    .stRadio div[role="radiogroup"] { flex-direction: row !important; gap: 10px; }
    .stRadio div[role="radiogroup"] label { 
        background: #1a1a2e; border: 1px solid var(--border); padding: 5px 20px !important; border-radius: 4px; color: var(--dim); font-weight: 800; cursor: pointer; transition: 0.3s;
    }
    .stRadio div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child { display: none; }
    .stRadio div[role="radiogroup"] label:hover { border-color: var(--green); }
    
    /* 자석 강도 카드 */
    .magnet-card { 
        background: linear-gradient(90deg, rgba(255,140,0,0.1) 0%, rgba(5,5,10,1) 100%);
        border-left: 5px solid var(--orange); padding: 15px; border-radius: 4px; margin: 15px 0;
        display: flex; justify-content: space-between; align-items: center;
    }
    .magnet-val { font-size: 24px; font-weight: 900; color: var(--orange); }
    .status-tag { padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 800; }

    /* 로그 컨테이너 */
    .briefing-container { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 15px; height: 280px; overflow-y: auto; margin-top: 20px; border-top: 2px solid var(--gold); }
    .log-entry { padding: 6px 0; border-bottom: 1px solid #1a1a2e; font-size: 13px; font-family: 'JetBrains Mono'; }
    </style>
    """, unsafe_allow_html=True)

# 3. 데이터 엔진 (자석 강도 로직 통합)
def safe_api_call(url, payload=None, is_post=True):
    try:
        if is_post: res = requests.post(url, json=payload, timeout=10)
        else: res = requests.get(url, timeout=10)
        return res.json() if res.status_code == 200 else None
    except: return None

@st.cache_data(ttl=12)
def fetch_all_data(coin, period):
    # 가격 정보
    mids = safe_api_call("https://api.hyperliquid.xyz/info", {"type": "allMids"})
    px = float(mids[coin]) if mids and coin in mids else 0
    if px == 0: return None
    
    # 하이퍼리퀴드 고래 데이터 (최대 150명 분석)
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

    # 자석 강도 연산: 현재가 ±1% 이내 잠재 물량 + 바이낸스 실제 청산
    potential_vol = sum(p['posVal'] for p in hl_pos if px * 0.99 <= p['liqPx'] <= px * 1.01)
    bn_res = safe_api_call(f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={coin}USDT&limit=50", is_post=False)
    actual_liq = sum(float(o['origQty']) * float(o['price']) for o in bn_res) if isinstance(bn_res, list) else 0
    
    return {"price": px, "positions": hl_pos, "magnet": (potential_vol + actual_liq) / 1e6, "actual": actual_liq / 1e6}

# 4. 메인 실행 파트
if 'briefing_history' not in st.session_state: st.session_state.briefing_history = []
if 'last_coin' not in st.session_state: st.session_state.last_coin = None

# 헤더
h_col1, h_col2 = st.columns([2, 1])
with h_col1:
    st.markdown(f"<h1 style='color:var(--green); margin:0; font-weight:900; font-size:32px;'>🐋 LIQUIDATION INTELLIGENCE PRO</h1>", unsafe_allow_html=True)
with h_col2:
    coin = st.radio("COIN", ["BTC", "ETH", "SOL"], horizontal=True, label_visibility="collapsed")

# 코인 변경 감지 로그
if st.session_state.last_coin != coin:
    add_log(f"분석 코인이 <b>{coin}</b>으로 스위칭되었습니다.", "info")
    st.session_state.last_coin = coin

data = fetch_all_data(coin, st.session_state.get('period', "24H"))

if data:
    px, magnet_score, actual_m = data['price'], data['magnet'], data['actual']
    all_pos = data['positions']
    
    # 상태값 판별
    status = "STABLE"
    status_color = "#6b6b7b"
    if magnet_score > 5: status, status_color = "WARNING", "#ff8c00"
    if magnet_score > 15: status, status_color = "CRITICAL", "#ff3e3e"
    
    if actual_m > 0.3:
        add_log(f"🔥 바이낸스 실시간 청산 감지: <b>${actual_m:.2f}M</b>", "danger")

    # 상단 자석 강도 UI
    st.markdown(f"""
        <div class="magnet-card">
            <div>
                <span style="color:var(--dim); font-size:12px;">{coin} 청산 자석 강도 (잠재+실시간)</span><br>
                <span class="status-tag" style="background:{status_color}; color:#000;">{status}</span>
            </div>
            <div class="magnet-val">${magnet_score:.2f}M</div>
        </div>
    """, unsafe_allow_html=True)

    # 필터 컨트롤러
    cc = st.columns([1, 1, 1, 1])
    with cc[0]: period = st.selectbox("분석 그룹", ["24H", "48H", "1W", "ALL"], index=["24H", "48H", "1W", "ALL"].index(st.session_state.get('period', "24H")))
    with cc[1]: range_p = st.selectbox("표시 범위 %", [1, 2, 5, 10, 15, 20, 25], index=3)
    step_list = [0.1, 0.5, 1, 5, 10, 50, 100]
    default_step = 10 if coin == "BTC" else (1 if coin == "ETH" else 0.5)
    with cc[2]: step_s = st.selectbox("사다리 정밀도 $", step_list, index=step_list.index(default_step))
    with cc[3]: min_val = st.number_input("최소 물량 필터", value=0)

    if period != st.session_state.get('period', "24H"):
        st.session_state.period = period
        add_log(f"분석 데이터 셋이 {period} 기준으로 갱신되었습니다.", "warning")
        st.rerun()

    # 사다리 연산
    tL, tS = sum(p['posVal'] for p in all_pos if p['isLong']), sum(p['posVal'] for p in all_pos if not p['isLong'])
    lo, hi = px * (1 - range_p/100), px * (1 + range_p/100)
    ladder = {}
    for p in all_pos:
        liq = p['liqPx']
        if lo <= liq <= hi:
            b = round(liq / step_s) * step_s
            if b not in ladder: ladder[b] = {"L": 0, "S": 0}
            if p['isLong']: ladder[b]["L"] += p['posVal']
            else: ladder[b]["S"] += p['posVal']

    magnets = {p: (v['L']+v['S']) / ((abs(p-px)/px*100 + 0.1)**1.5) for p, v in ladder.items()}
    golden = sorted(magnets, key=magnets.get, reverse=True)[:5] if magnets else []
    max_v, max_d = max([v["L"] + v["S"] for v in ladder.values()] + [1]), max([abs(v["S"] - v["L"]) for v in ladder.values()] + [1])
    
    whales = sorted(all_pos, key=lambda x: x['posVal'], reverse=True)[:10]
    for w in whales:
        # 고래 평단가 추정 (레버리지 5배 가정)
        w['ent'] = w['liqPx'] / (1 - 0.2) if w['isLong'] else w['liqPx'] / (1 + 0.2)
        w['isP'] = (px > w['ent']) if w['isLong'] else (px < w['ent'])

    payload = json.dumps({"price": px, "map": ladder, "whales": whales, "maxV": max_v, "maxD": max_d, "gold": golden, "coin": coin, "minV": min_val, "tL": tL, "tS": tS})

    # 시각화 컴포넌트 (HTML/JS)
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@600;800&display=swap" rel="stylesheet">
        <style>
            :root{{--bg:#05050a;--card:#0e0e1a;--ln:#1e1e30;--g:#00ffa3;--r:#ff3e3e;--gold:#ffcc00;--cyan:#00f2ff;--orange:#ff8c00;--dim:#6b6b7b;}}
            body{{background:var(--bg); color:#e1e1e6; font-family:'JetBrains Mono', monospace; margin:0; padding:10px; overflow-x:hidden;}}
            #wCard{{display:grid; grid-template-columns: repeat(5, 1fr); gap:12px; margin-bottom:20px;}}
            .wc{{background:var(--card); border:1px solid var(--ln); padding:15px; border-radius:8px; font-size:14px; position:relative; line-height:1.6;}}
            .pl-tag{{position:absolute; top:12px; right:12px; font-size:9px; font-weight:800; padding:2px 5px; border-radius:4px;}}
            .profit{{background:rgba(0,255,163,0.15); color:var(--g);}} .loss{{background:rgba(255,62,62,0.15); color:var(--r);}}
            #deltaBar{{margin:15px 0; height:45px; background:var(--card); border-radius:8px; display:flex; overflow:hidden; font-size:16px; font-weight:800; border:1px solid var(--ln)}}
            #dL{{background:var(--g); color:#000; display:flex; align-items:center; padding:0 25px;}}
            #dS{{background:var(--r); color:#000; display:flex; align-items:center; justify-content:flex-end; padding:0 25px;}}
            .row{{display:grid; grid-template-columns: 110px 70px 1.5fr 110px 90px; height:24px; align-items:center; gap:12px; margin-bottom:2px; padding:0 10px;}}
            .row.golden{{border: 1px solid var(--gold); background: rgba(255, 204, 0, 0.08);}}
            .px{{text-align:right; font-weight:800; color:#fff; font-size:14px;}}
            .bc{{height:14px; background:#121221; border-radius:2px; position:relative; overflow:hidden;}}
            .bar{{height:100%; position:absolute;}}
            .curB{{height:55px; background:rgba(255,204,0,0.12); color:var(--gold); display:flex; align-items:center; justify-content:center; font-weight:800; margin:15px 0; border:1px solid rgba(255,204,0,0.4); font-size:22px; border-radius:8px;}}
        </style>
    </head>
    <body>
        <div id="wCard"></div>
        <div id="deltaBar"><div id="dL">LONG</div><div id="dS">SHORT</div></div>
        <div id="main"></div>
        <script>
            const d = {payload};
            document.getElementById('wCard').innerHTML = d.whales.map(f => `
                <div class="wc">
                    <span class="pl-tag ${{f.isP?'profit':'loss'}}">${{f.isP?'PROFIT':'LOSS'}}</span>
                    ID: <b style="color:var(--gold)">${{f.user}}</b> | <span style="color:${{f.isLong?'var(--g)':'var(--r)'}}">${{f.isLong?'L':'S'}}</span><br>
                    SZ: <b>$${{(f.posVal/1e6).toFixed(1)}}M</b><br>
                    ENT: <b>$${{f.ent.toLocaleString(undefined, {{maximumFractionDigits:d.coin==='BTC'?0:2}})}}</b><br>
                    LIQ: <b style="color:var(--cyan)">$${{f.liqPx.toLocaleString(undefined, {{maximumFractionDigits:d.coin==='BTC'?0:2}})}}</b>
                </div>
            `).join('');
            const lPct = (d.tL / (d.tL + d.tS || 1)) * 100;
            document.getElementById('dL').style.flex = lPct; document.getElementById('dS').style.flex = 100 - lPct;
            document.getElementById('dL').innerHTML = `L ${{Math.round(lPct)}}%`;
            document.getElementById('dS').innerHTML = `${{Math.round(100-lPct)}}% S`;
            const prices = Object.keys(d.map).map(Number).sort((a,b)=>b-a);
            let html = ''; let mid = false;
            prices.forEach(p => {{
                const data = d.map[p];
                if(!mid && p <= d.price) {{ html += `<div class="curB">${{d.coin}} MARKET PRICE: $${{d.price.toLocaleString()}}</div>`; mid = true; }}
                if((data.L + data.S) < d.minV) return;
                const isGold = d.gold.includes(p);
                html += `<div class="row ${{isGold ? 'golden' : ''}}">
                    <div class="px">$${{p.toLocaleString(undefined, {{minimumFractionDigits:d.coin==='BTC'?0:1}})}}</div>
                    <div class="pct" style="text-align:right; font-size:11px; color:var(--dim);">${{(((p-d.price)/d.price)*100).toFixed(1)}}%</div>
                    <div class="bc"><div class="bar" style="width:${{(data.L/d.maxV)*100}}%; background:var(--g); left:0; position:absolute;"></div><div class="bar" style="width:${{(data.S/d.maxV)*100}}%; background:var(--r); right:0; position:absolute;"></div></div>
                    <div style="height:10px; background:#1a1a2e; border-radius:2px; position:relative; overflow:hidden;"><div style="height:100%; width:${{(Math.abs(data.S-data.L)/d.maxD)*100}}%; background:${{data.S>=data.L?'var(--cyan)':'var(--orange)'}}; margin-left:${{data.S<data.L?'auto':'0'}}"></div></div>
                    <div style="font-size:12px; color:var(--cyan); font-weight:800; text-align:right;">$${{((data.L+data.S)/1e6).toFixed(1)}}M</div>
                </div>`;
            }});
            document.getElementById('main').innerHTML = html;
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=1200, scrolling=True)

    # 하단 브리핑 로그
    st.markdown(f"<h3 style='color:var(--gold); margin-top:30px; font-size:18px; font-weight:900;'>📡 통합 실시간 분석 로그</h3>", unsafe_allow_html=True)
    briefing_html = "".join(st.session_state.briefing_history[:50])
    st.markdown(f'<div class="briefing-container">{briefing_html}</div>', unsafe_allow_html=True)
