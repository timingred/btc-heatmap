import streamlit as st
import streamlit.components.v1 as components
import json, requests, time, pandas as pd
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# 1. 페이지 설정 및 초기화 (오류 방지를 위해 최상단 배치)
st.set_page_config(page_title="TIMINGBIT LIQUIDATION INTELLIGENCE", layout="wide")

if 'period' not in st.session_state: st.session_state.period = "24H"
if 'last_liq_time' not in st.session_state: st.session_state.last_liq_time = 0
if 'cvd_val' not in st.session_state: st.session_state.cvd_val = 0.0
# 히스토리컬 히트맵용 저장 바구니
if 'heat_history' not in st.session_state: st.session_state.heat_history = pd.DataFrame(columns=['price', 'liq', 'time'])

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

# 2. 전역 스타일 (티커 흰색 가독성 및 디자인 강화)
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');
    :root { 
        --bg: #05050a; --card: #0e0e1a; --border: #1e1e30; 
        --green: #00ffa3; --red: #ff3e3e; --cyan: #00f2ff; --orange: #ff8c00; --dim: #6b6b7b; 
    }
    .stApp {background-color: var(--bg); color: #e1e1e6;}
    .block-container {padding: 0.5rem 2rem !important; max-width: 100%; font-family: 'JetBrains Mono', sans-serif !important;}
    [data-testid="stHeader"] {display: none;}
    
    /* 티커 버튼 화이트 고정 */
    .stRadio div[role="radiogroup"] { flex-direction: row !important; gap: 15px; }
    .stRadio div[role="radiogroup"] label { 
        background: #1a1a2e !important; border: 2px solid var(--border) !important; padding: 10px 45px !important; border-radius: 8px !important; 
        color: #FFFFFF !important; font-size: 22px !important; font-weight: 900 !important; cursor: pointer; transition: 0.2s;
    }
    .stRadio div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child { display: none; }
    div[data-testid="stMarkdownContainer"] + div .stRadio div[role="radiogroup"] label[data-checked="true"] {
        border-color: var(--green) !important; background: rgba(0, 255, 163, 0.2) !important;
        box-shadow: 0 0 15px rgba(0, 255, 163, 0.4);
    }

    .analysis-card { background: var(--card); border: 1px solid var(--border); padding: 18px; border-radius: 12px; height: 180px; position: relative; }
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
def fetch_terminal_data(coin, period_label):
    # 가격
    mids = safe_api_call("https://api.hyperliquid.xyz/info", payload={"type": "allMids"})
    px = float(mids[coin]) if mids and coin in mids else 0
    
    # 바이낸스 실시간 청산 (Sweep 감지 & CVD용)
    bn_res = safe_api_call(f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={coin}USDT&limit=100", is_post=False)
    actual_m = sum(float(o['origQty']) * float(o['price']) for o in bn_res) / 1e6 if isinstance(bn_res, list) else 0

    # 고래 데이터 (인원 확대 유지)
    cfg_map = {"24H": 150, "48H": 200, "3D": 250, "1W": 300, "2W": 400, "1M": 500, "ALL": 800}
    lb = safe_api_call(f"https://stats-data.hyperliquid.xyz/Mainnet/leaderboard?window=day", is_post=False)
    hl_pos = []
    if lb:
        addrs = [r["ethAddress"] for r in lb.get("leaderboardRows", [])[:cfg_map.get(period_label, 150)] if r.get("ethAddress")]
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

    # 자석 범위 확장 보정
    scan_range = 0.02 if coin == "BTC" else 0.05
    potential_vol = sum(p['posVal'] for p in hl_pos if px * (1-scan_range) <= p['liqPx'] <= px * (1+scan_range))
    
    return {"price": px, "bn_orders": bn_res, "positions": hl_pos, "magnet": (potential_vol/1e6)+actual_m}

# 4. 메인 대시보드
h1, h2 = st.columns([2.5, 1])
with h1: st.markdown("<h1 style='color:var(--green); margin:0; font-weight:900;'>🐋 TIMINGBIT LIQUIDATION INTELLIGENCE</h1>", unsafe_allow_html=True)
with h2: coin = st.radio("COIN", ["BTC", "ETH"], horizontal=True, label_visibility="collapsed")

data = fetch_terminal_data(coin, st.session_state.period)

if data:
    px, bn_orders, magnet_score, all_pos = data['price'], data['bn_orders'], data['magnet'], data['positions']
    
    # CVD 및 히트맵 데이터 연산
    current_cvd = 0.0
    new_heats = []
    if isinstance(bn_orders, list):
        for o in bn_orders:
            o_time = int(o['time'])
            if o_time > st.session_state.last_liq_time:
                val = float(o['origQty']) * float(o['price'])
                if o['side'] == 'SELL': current_cvd += val
                else: current_cvd -= val
                new_heats.append({"price": float(o['price']), "liq": val / 1e6, "time": o_time})
                st.session_state.last_liq_time = max(st.session_state.last_liq_time, o_time)
    
    # CVD 누적 및 히트맵 저장
    st.session_state.cvd_val += (current_cvd / 1e6)
    if new_heats:
        new_df = pd.DataFrame(new_heats)
        st.session_state.heat_history = pd.concat([st.session_state.heat_history, new_df]).tail(500) # 최근 500개 유지

    # 상단 분석 카드
    a1, a2 = st.columns(2)
    with a1:
        sfp_color = "var(--green)" if current_cvd > 1.0 or current_cvd < -1.0 else "var(--dim)"
        st.markdown(f'<div class="analysis-card" style="border-top:4px solid {sfp_color};"><div style="color:var(--dim); font-size:11px;">SMART MONEY SIGNAL (SFP)</div><div style="font-size:24px; font-weight:900; color:{sfp_color}; margin:10px 0;">{"🚨 LIQUIDITY SWEEP 감지" if current_cvd > 1.0 or current_cvd < -1.0 else "SCANNING..."}</div><div style="font-size:13px; color:#aaa; line-height:1.5;">{"세력이 유동성확보 패턴(Sweep)을 만들었습니다. 반전 타점에 주의하세요!" if current_cvd > 1.0 or current_cvd < -1.0 else "유의미한 유동성 휩쓸기 패턴을 추적 중입니다."}</div></div>', unsafe_allow_html=True)
    with a2:
        s_tag, s_color = ("CRITICAL", "var(--red)") if magnet_score > 15 else (("WARNING", "var(--orange)") if magnet_score > 8 else ("STABLE", "#6b6b7b"))
        st.markdown(f'<div class="analysis-card" style="border-top:4px solid {s_color};"><div style="color:var(--dim); font-size:11px;">LIQUIDATION MAGNET</div><div style="font-size:32px; font-weight:900; color:{s_color}; margin:10px 0;">${magnet_score:.2f}M</div><div style="margin-top:5px;"><span class="status-tag" style="background:{s_color};">{s_tag}</span></div><div style="position:absolute; bottom:15px; font-size:11px; color:var(--dim);">현재가 근처 잠재적 청산 폭발력 (CVD기반)</div></div>', unsafe_allow_html=True)

    # 필터
    p_list = ["24H", "48H", "3D", "1W", "2W", "1M", "ALL"]
    c1, c2, c3, c4 = st.columns(4)
    with c1: 
        selected_p = st.selectbox("분석 그룹 (기간)", p_list, index=p_list.index(st.session_state.period))
        if selected_p != st.session_state.period:
            st.session_state.period = selected_p
            # 코인/기간 스위칭 시 히스토리 초기화 (데이터 꼬임 방지)
            st.session_state.cvd_val = 0.0
            st.session_state.last_liq_time = 0
            st.session_state.heat_history = pd.DataFrame(columns=['price', 'liq', 'time'])
            st.rerun()
    with c2: range_p = st.selectbox("표시 범위 %", [1, 2, 5, 10, 15, 20, 30, 50], index=4)
    with c3: step_s = st.selectbox("사다리 정밀도 $", [1, 5, 10, 50, 100], index=2)
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
    
    # Historical Heatmap 데이터 정렬 (시간 내림차순)
    heat_json = st.session_state.heat_history.to_json(orient='records')

    # 사다리 맵 + Historical Heatmap 통합 시각화 (HTML)
    max_v = max([v["L"] + v["S"] for v in ladder.values()] + [1])
    max_d = max([abs(v["S"] - v["L"]) for v in ladder.values()] + [1])
    whales = sorted(all_pos, key=lambda x: x['posVal'], reverse=True)[:15]
    payload = json.dumps({"price": px, "map": ladder, "whales": whales, "maxV": max_v, "maxD": max_d, "coin": coin, "minV": min_val, "tL": sum(p['posVal'] for p in all_pos if p['isLong']), "tS": sum(p['posVal'] for p in all_pos if not p['isLong'])})

    html_code = f"""
    <!DOCTYPE html><html><head><link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@600;800&display=swap" rel="stylesheet"><style>
    :root{{--bg:#05050a;--card:#0e0e1a;--ln:#1e1e30;--g:#00ffa3;--r:#ff3e3e;--gold:#ffcc00;--cyan:#00f2ff;--orange:#ff8c00;--dim:#6b6b7b;}}
    body{{background:var(--bg); color:#e1e1e6; font-family:'JetBrains Mono', monospace; margin:0; padding:10px; overflow:hidden;}}
    #wCard{{display:grid; grid-template-columns: repeat(5, 1fr); gap:12px; margin-bottom:20px;}}
    .wc{{background:var(--card); border:1px solid var(--ln); padding:15px; border-radius:8px; font-size:14px; position:relative; line-height:1.6;}}
    .pl-tag{{position:absolute; top:12px; right:12px; font-size:9px; font-weight:800; padding:2px 5px; border-radius:4px;}}
    .profit{{background:rgba(0,255,163,0.15); color:var(--g);}} .loss{{background:rgba(255,62,62,0.15); color:var(--r);}}
    #deltaBar{{margin:15px 0; height:45px; background:var(--card); border-radius:8px; display:flex; overflow:hidden; font-size:16px; font-weight:800; border:1px solid var(--ln)}}
    #dL{{background:var(--g); color:#000; display:flex; align-items:center; padding:0 25px;}} #dS{{background:var(--r); color:#000; display:flex; align-items:center; justify-content:flex-end; padding:0 25px;}}
    
    /* 통합 레이아웃 (Ladder + Heatmap) */
    #main-container {{display: grid; grid-template-columns: 1fr 180px; gap: 15px;}}
    #ladder-map {{display: grid; grid-template-rows: repeat(auto-fill, 24px);}}
    #heatmap-timeline {{display: grid; grid-template-rows: repeat(auto-fill, 24px); border-left: 1px solid var(--border);}}

    .row{{display:grid; grid-template-columns: 110px 70px 1.5fr 110px 90px; height:24px; align-items:center; gap:12px; margin-bottom:2px; padding:0 10px;}}
    .px{{text-align:right; font-weight:800; color:#fff; font-size:14px;}}
    .bc{{height:14px; background:#121221; border-radius:2px; position:relative; overflow:hidden;}} .bar{{height:100%; position:absolute;}}
    .curB{{height:55px; background:rgba(255,204,0,0.12); color:var(--gold); display:flex; align-items:center; justify-content:center; font-weight:800; margin:15px 0; border:1px solid rgba(255,204,0,0.4); font-size:22px; border-radius:8px;}}
    
    /* Heatmap 스타일 */
    .heat-bar {{height: 10px; background: var(--border); border-radius: 2px;}}
    </style></head><body><div id="wCard"></div><div id="deltaBar"><div id="dL">LONG</div><div id="dS">SHORT</div></div>
    
    <div id="main-container">
        <div id="ladder-map"></div>
        <div id="heatmap-timeline"></div>
    </div>

    <script>
    const d = {payload};
    const h = {heat_json};
    const max_heat = Math.max(...h.map(i=>i.liq)) || 1;

    document.getElementById('wCard').innerHTML = d.whales.map(f => `<div class="wc"><span class="pl-tag ${{f.isP?'profit':'loss'}}">${{f.isP?'PROFIT':'LOSS'}}</span>ID: <b style="color:var(--gold)">${{f.user}}</b> | <span style="color:${{f.isLong?'var(--g)':'var(--r)'}}">${{f.isLong?'L':'S'}}</span><br>SZ: <b>$${{(f.posVal/1e6).toFixed(1)}}M</b><br>ENT: <b>$${{(f.liqPx/0.8).toLocaleString(undefined, {{maximumFractionDigits:d.coin==='BTC'?0:2}})}}</b><br>LIQ: <b style="color:var(--cyan)">$${{f.liqPx.toLocaleString(undefined, {{maximumFractionDigits:d.coin==='BTC'?0:2}})}}</b></div>`).join('');
    
    const lPct = (d.tL / (d.tL + d.tS || 1)) * 100; document.getElementById('dL').style.flex = lPct; document.getElementById('dS').style.flex = 100 - lPct; document.getElementById('dL').innerHTML = `L ${{Math.round(lPct)}}%`; document.getElementById('dS').innerHTML = `${{Math.round(100-lPct)}}% S`;
    
    const prices = Object.keys(d.map).map(Number).sort((a,b)=>b-a); 
    let ladderHtml = ''; let heatHtml = ''; let mid = false;
    
    prices.forEach(p => {{ 
        const data = d.map[p]; 
        if(!mid && p <= d.price) {{ 
            ladderHtml += `<div class="curB">${{d.coin}} MARKET PRICE: $${{d.price.toLocaleString()}}</div>`; 
            heatHtml += `<div style="height:55px;"></div>`;
            mid = true; 
        }} 
        if((data.L + data.S) < d.minV) return; 

        ladderHtml += `<div class="row"><div class="px">$${{p.toLocaleString(undefined, {{minimumFractionDigits:d.coin==='BTC'?0:1}})}}</div><div class="pct" style="text-align:right; font-size:11px; color:var(--dim);">${{(((p-d.price)/d.price)*100).toFixed(1)}}%</div><div class="bc"><div class="bar" style="width:${{(data.L/d.maxV)*100}}%; background:var(--g); left:0; position:absolute;"></div><div class="bar" style="width:${{(data.S/d.maxV)*100}}%; background:var(--r); right:0; position:absolute;"></div></div><div style="height:10px; background:#1a1a2e; border-radius:2px; position:relative; overflow:hidden;"><div style="height:100%; width:${{(Math.abs(data.S-data.L)/d.maxD)*100}}%; background:${{data.S>=data.L?'var(--cyan)':'var(--orange)'}}; margin-left:${{data.S<data.L?'auto':'0'}}"></div></div><div style="font-size:12px; color:var(--cyan); font-weight:800; text-align:right;">$${{((data.L+data.S)/1e6).toFixed(1)}}M</div></div>`; 

        // Heatmap 타임라인 빌드 (과거 데이터 중 해당 가격대 검색)
        const current_heat = h.find(i => Math.abs(i.price - p) < (d.coin==='BTC'?5:1)) || {{liq:0}};
        heatHtml += `<div style="height:24px; display:flex; align-items:center; gap:5px; padding:0 10px;">
            <div class="heat-bar" style="width:${{(current_heat.liq/max_heat)*100}}%; background: var(--green);"></div>
            <span style="font-size:10px; color:var(--green);">${{current_heat.liq>0 ? current_heat.liq.toFixed(1)+'M':''}}</span>
        </div>`;
    }});
    
    document.getElementById('ladder-map').innerHTML = ladderHtml;
    document.getElementById('heatmap-timeline').innerHTML = heatHtml;
    </script></body></html>
    """
    components.html(html_code, height=1200, scrolling=True)
