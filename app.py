import streamlit as st
import streamlit.components.v1 as components
import json, requests, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# 1. 페이지 설정 및 초기화
st.set_page_config(page_title="TIMINGBIT LIQUIDATION INTELLIGENCE", layout="wide")

if 'briefing_history' not in st.session_state: st.session_state.briefing_history = []
if 'period' not in st.session_state: st.session_state.period = "24H"

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def add_log(msg, log_type="info"):
    colors = {"info": "#6b6b7b", "success": "#00ffa3", "warning": "#ff8c00", "danger": "#ff3e3e"}
    now = get_kst_now().strftime("%H:%M:%S")
    log_entry = f'<div class="log-entry" style="color:{colors.get(log_type, "#6b6b7b")}"><span style="color:#444">[ {now} ]</span> {msg}</div>'
    st.session_state.briefing_history.insert(0, log_entry)

# 2. 전역 스타일 (티커 시인성 및 카드 디자인)
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');
    :root { --bg: #05050a; --card: #0e0e1a; --border: #1e1e30; --green: #00ffa3; --red: #ff3e3e; --cyan: #00f2ff; --gold: #ffcc00; --dim: #6b6b7b; }
    .stApp {background-color: var(--bg); color: #e1e1e6;}
    .block-container {padding: 1rem 2rem !important; max-width: 100%; font-family: 'JetBrains Mono', sans-serif !important;}
    [data-testid="stHeader"] {display: none;}
    
    /* 티커 화이트 고정 */
    .stRadio div[role="radiogroup"] label { 
        background: #1a1a2e !important; border: 2px solid var(--border) !important; padding: 10px 45px !important; border-radius: 8px !important; 
        color: #FFFFFF !important; font-size: 20px !important; font-weight: 900 !important; cursor: pointer;
    }
    div[data-testid="stMarkdownContainer"] + div .stRadio div[role="radiogroup"] label[data-checked="true"] {
        border-color: var(--green) !important; background: rgba(0, 255, 163, 0.15) !important;
    }

    .analysis-card { background: var(--card); border: 1px solid var(--border); padding: 18px; border-radius: 12px; min-height: 200px; position: relative; }
    .val-main { font-size: 28px; font-weight: 900; margin: 8px 0; }
    .sub-label { color: var(--dim); font-size: 11px; text-transform: uppercase; }
    .price-tag { background: rgba(0, 242, 255, 0.1); color: var(--cyan); padding: 2px 6px; border-radius: 4px; font-weight: 800; }
    .briefing-container { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 15px; height: 300px; overflow-y: auto; margin-top: 20px; border-top: 2px solid var(--gold); }
    .log-entry { padding: 6px 0; border-bottom: 1px solid #1a1a2e; font-size: 13px; font-family: 'JetBrains Mono'; }
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
def fetch_smc_data(coin, period_label):
    mids = safe_api_call("https://api.hyperliquid.xyz/info", payload={"type": "allMids"})
    px = float(mids[coin]) if mids and coin in mids else 0
    bn_res = safe_api_call(f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={coin}USDT&limit=100", is_post=False)
    actual_m = sum(float(o['origQty']) * float(o['price']) for o in bn_res) / 1e6 if isinstance(bn_res, list) else 0
    
    # 기간별 분석 데이터 범위 설정 (복구 완료)
    window_map = {"24H": "day", "48H": "day", "3D": "day", "1W": "week", "2W": "week", "1M": "allTime", "ALL": "allTime"}
    cfg_map = {"24H": 150, "48H": 200, "3D": 250, "1W": 300, "2W": 400, "1M": 500, "ALL": 1000}
    
    window = window_map.get(period_label, "day")
    user_count = cfg_map.get(period_label, 150)
    
    lb = safe_api_call(f"https://stats-data.hyperliquid.xyz/Mainnet/leaderboard?window={window}", is_post=False)
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
    return {"price": px, "bn_liq": actual_m, "positions": hl_pos}

# 4. 메인 실행
h1, h2 = st.columns([2.5, 1])
with h1: st.markdown("<h1 style='color:var(--green); margin:0; font-weight:900;'>🐋 TIMINGBIT LIQUIDATION INTELLIGENCE</h1>", unsafe_allow_html=True)
with h2: coin = st.radio("COIN", ["BTC", "ETH"], horizontal=True, label_visibility="collapsed")

# 7단계 기간 리스트 복구
p_list = ["24H", "48H", "3D", "1W", "2W", "1M", "ALL"]

data = fetch_smc_data(coin, st.session_state.period)

if data:
    px, actual_m, all_pos = data['price'], data['bn_liq'], data['positions']
    
    # 필터 컨트롤러
    c1, c2, c3, c4 = st.columns(4)
    with c1: 
        selected_p = st.selectbox("분석 그룹 (기간)", p_list, index=p_list.index(st.session_state.period))
        if selected_p != st.session_state.period:
            st.session_state.period = selected_p
            st.rerun()
    with c2: range_p = st.selectbox("표시 범위 %", [5, 10, 15, 20, 30, 50], index=1)
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

    # 타점 분석 엔진
    prices = sorted(ladder.keys())
    gaps = []
    max_wall = max([v['L'] + v['S'] for v in ladder.values()]) if ladder else 1
    for i in range(len(prices)-1):
        if (ladder[prices[i]]['L'] + ladder[prices[i]]['S']) < (max_wall * 0.1): gaps.append(prices[i])
    sweep_intensity = (actual_m / (max_wall/1e6)) * 100 if max_wall > 0 else 0
    
    a1, a2 = st.columns(2)
    with a1:
        sfp_color = "var(--green)" if sweep_intensity > 50 else "var(--dim)"
        st.markdown(f'<div class="analysis-card" style="border-top:4px solid {sfp_color};"><div class="sub-label">SFP Sweep Intensity</div><div class="val-main" style="color:{sfp_color};">{sweep_intensity:.1f}%</div><div style="font-size:13px; color:#aaa;">{"🚨 <b>세력 매집 완료!</b> 반전 타점 발생" if sweep_intensity > 50 else "유동성 확보 패턴 분석 중..."}</div><div style="margin-top:15px; font-size:12px;">추천 대응: <span class="price-tag">{coin} {"숏(Short)" if px > (sum(prices)/len(prices) if prices else px) else "롱(Long)"} 진입 대기</span></div></div>', unsafe_allow_html=True)
    with a2:
        gap_start, gap_end = (min(gaps), max(gaps)) if gaps else (0, 0)
        st.markdown(f'<div class="analysis-card" style="border-top:4px solid var(--cyan);"><div class="sub-label">Liquidity High-Speed Zone</div><div class="val-main" style="color:var(--cyan);">${gap_end - gap_start:,.0f} GAP</div><div style="font-size:13px; color:#aaa; margin-bottom:10px;">변동성 폭발 구간: <span class="price-tag">${gap_start:,.0f} ~ ${gap_end:,.0f}</span></div><div style="font-size:11px; color:var(--dim);">이 구간 진입 시 저항 없이 가격이 빠르게 밀릴 수 있습니다.</div></div>', unsafe_allow_html=True)

    # 사다리 맵 시각화
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
    .row{{display:grid; grid-template-columns: 110px 70px 1.5fr 110px 90px; height:24px; align-items:center; gap:12px; margin-bottom:2px; padding:0 10px;}}
    .px{{text-align:right; font-weight:800; color:#fff; font-size:14px;}}
    .bc{{height:14px; background:#121221; border-radius:2px; position:relative; overflow:hidden;}} .bar{{height:100%; position:absolute;}}
    .curB{{height:55px; background:rgba(255,204,0,0.12); color:var(--gold); display:flex; align-items:center; justify-content:center; font-weight:800; margin:15px 0; border:1px solid rgba(255,204,0,0.4); font-size:22px; border-radius:8px;}}
    </style></head><body><div id="wCard"></div><div id="deltaBar"><div id="dL">LONG</div><div id="dS">SHORT</div></div><div id="main"></div><script>
    const d = {payload}; document.getElementById('wCard').innerHTML = d.whales.map(f => `<div class="wc"><span class="pl-tag ${{f.isP?'profit':'loss'}}">${{f.isP?'PROFIT':'LOSS'}}</span>ID: <b style="color:var(--gold)">${{f.user}}</b> | <span style="color:${{f.isLong?'var(--g)':'var(--r)'}}">${{f.isLong?'L':'S'}}</span><br>SZ: <b>$${{(f.posVal/1e6).toFixed(1)}}M</b><br>LIQ: <b style="color:var(--cyan)">$${{f.liqPx.toLocaleString(undefined, {{maximumFractionDigits:d.coin==='BTC'?0:2}})}}</b></div>`).join('');
    const lPct = (d.tL / (d.tL + d.tS || 1)) * 100; document.getElementById('dL').style.flex = lPct; document.getElementById('dS').style.flex = 100 - lPct; document.getElementById('dL').innerHTML = `L ${{Math.round(lPct)}}%`; document.getElementById('dS').innerHTML = `${{Math.round(100-lPct)}}% S`;
    const prices = Object.keys(d.map).map(Number).sort((a,b)=>b-a); let html = ''; let mid = false; prices.forEach(p => {{ const data = d.map[p]; if(!mid && p <= d.price) {{ html += `<div class="curB">${{d.coin}} MARKET PRICE: $${{d.price.toLocaleString()}}</div>`; mid = true; }} if((data.L + data.S) < d.minV) return; html += `<div class="row"><div class="px">$${{p.toLocaleString(undefined, {{minimumFractionDigits:d.coin==='BTC'?0:1}})}}</div><div class="pct" style="text-align:right; font-size:11px; color:var(--dim);">${{(((p-d.price)/d.price)*100).toFixed(1)}}%</div><div class="bc"><div class="bar" style="width:${{(data.L/d.maxV)*100}}%; background:var(--g); left:0; position:absolute;"></div><div class="bar" style="width:${{(data.S/d.maxV)*100}}%; background:var(--r); right:0; position:absolute;"></div></div><div style="height:10px; background:#1a1a2e; border-radius:2px; position:relative; overflow:hidden;"><div style="height:100%; width:${{(Math.abs(data.S-data.L)/d.maxD)*100}}%; background:${{data.S>=data.L?'var(--cyan)':'var(--orange)'}}; margin-left:${{data.S<data.L?'auto':'0'}}"></div></div><div style="font-size:12px; color:var(--cyan); font-weight:800; text-align:right;">$${{((data.L+data.S)/1e6).toFixed(1)}}M</div></div>`; }});
    document.getElementById('main').innerHTML = html;</script></body></html>
    """
    components.html(html_code, height=1200, scrolling=True)
    
    st.markdown(f"<h3 style='color:var(--gold); margin-top:30px; font-size:18px; font-weight:900;'>📡 통합 실시간 분석 로그</h3>", unsafe_allow_html=True)
    briefing_html = "".join(st.session_state.briefing_history[:50])
    st.markdown(f'<div class="briefing-container">{briefing_html}</div>', unsafe_allow_html=True)
