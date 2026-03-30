import streamlit as st
import streamlit.components.v1 as components
import json, requests, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# 1. 페이지 설정
st.set_page_config(page_title="TIMINGBIT LIQUIDATION INTELLIGENCE", layout="wide")

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

# 로그 기록
def add_log(msg, log_type="info"):
    colors = {"info": "#6b6b7b", "success": "#00ffa3", "warning": "#ff8c00", "danger": "#ff3e3e"}
    now = get_kst_now().strftime("%H:%M:%S")
    log_entry = f'<div class="log-entry" style="color:{colors.get(log_type, "#6b6b7b")}"><span style="color:#444">[ {now} ]</span> {msg}</div>'
    if 'briefing_history' not in st.session_state: st.session_state.briefing_history = []
    st.session_state.briefing_history.insert(0, log_entry)

# 2. 강력한 전역 스타일 (티커 흰색 고정 및 가독성 최적화)
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
    
    /* 티커 버튼 스타일 (흰색 글씨 강제) */
    .stRadio div[role="radiogroup"] { flex-direction: row !important; gap: 15px; }
    .stRadio div[role="radiogroup"] label { 
        background: #1a1a2e !important; border: 2px solid var(--border) !important; padding: 10px 45px !important; border-radius: 8px !important; 
        color: #FFFFFF !important; font-size: 22px !important; font-weight: 900 !important; cursor: pointer; transition: 0.3s;
    }
    .stRadio div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child { display: none; }
    .stRadio div[role="radiogroup"] label:hover { border-color: var(--green) !important; background: #252545 !important; }
    
    /* 선택된 코인 하이라이트 */
    div[data-testid="stMarkdownContainer"] + div .stRadio div[role="radiogroup"] label[data-checked="true"] {
        border-color: var(--green) !important;
        background: rgba(0, 255, 163, 0.2) !important;
        box-shadow: 0 0 15px rgba(0, 255, 163, 0.4);
    }

    .analysis-card { background: var(--card); border: 1px solid var(--border); padding: 20px; border-radius: 12px; height: 180px; position: relative; }
    .status-tag { padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 900; color: #000; text-transform: uppercase; }
    .briefing-container { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 15px; height: 300px; overflow-y: auto; margin-top: 20px; border-top: 2px solid var(--gold); }
    .log-entry { padding: 6px 0; border-bottom: 1px solid #1a1a2e; font-size: 13px; font-family: 'JetBrains Mono'; }
    </style>
    """, unsafe_allow_html=True)

# 3. 데이터 엔진 (검증 로직 강화)
def safe_api_call(url, payload=None, is_post=True):
    try:
        if is_post: res = requests.post(url, json=payload, timeout=8)
        else: res = requests.get(url, timeout=8)
        return res.json() if res.status_code == 200 else None
    except: return None

@st.cache_data(ttl=12)
def fetch_verified_data(coin, period_label):
    # 가격 정보
    mids = safe_api_call("https://api.hyperliquid.xyz/info", {"type": "allMids"})
    px = float(mids[coin]) if mids and coin in mids else 0
    
    # 바이낸스 실시간 OI
    oi_res = safe_api_call(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={coin}USDT", is_post=False)
    cur_oi = float(oi_res['openInterest']) if oi_res else 0
    
    # 바이낸스 실시간 청산액
    bn_res = safe_api_call(f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={coin}USDT&limit=100", is_post=False)
    actual_m = sum(float(o['origQty']) * float(o['price']) for o in bn_res) / 1e6 if isinstance(bn_res, list) else 0

    # 고래 리더보드 데이터
    cfg_map = {"24H": 150, "48H": 200, "3D": 250, "1W": 300, "2W": 400, "1M": 500, "ALL": 800}
    lb = safe_api_call(f"https://stats-data.hyperliquid.xyz/Mainnet/leaderboard?window=day", is_post=False)
    hl_pos = []
    if lb:
        addrs = [r["ethAddress"] for r in lb.get("leaderboardRows", [])[:cfg_map.get(period_label, 150)] if r.get("ethAddress")]
        def fetch_hl(a):
            d = safe_api_call("https://api.hyperliquid.xyz/info", {"type": "clearinghouseState", "user": a})
            if d and "assetPositions" in d:
                for ap in d["assetPositions"]:
                    p = ap.get("position")
                    if p and coin in str(p.get("coin", "")).upper():
                        return {"liqPx": float(p.get("liquidationPx") or 0), "posVal": float(p.get("positionValue") or 0), "isLong": float(p.get("szi") or 0) > 0, "user": a[:6]}
            return None
        with ThreadPoolExecutor(max_workers=40) as ex:
            hl_pos = [r for r in list(ex.map(fetch_hl, addrs)) if r]

    potential_vol = sum(p['posVal'] for p in hl_pos if px * 0.98 <= p['liqPx'] <= px * 1.02)
    return {"price": px, "oi": cur_oi, "actual": actual_m, "positions": hl_pos, "magnet": (potential_vol/1e6)+actual_m}

# 4. 메인 대시보드
if 'oi_history' not in st.session_state: st.session_state.oi_history = {}
if 'px_history' not in st.session_state: st.session_state.px_history = {}
if 'period' not in st.session_state: st.session_state.period = "24H"

# 상단 헤더
h_col1, h_col2 = st.columns([2, 1])
with h_col1:
    st.markdown(f"<h1 style='color:var(--green); margin:0; font-weight:900; font-size:36px;'>🐋 TIMINGBIT LIQUIDATION INTELLIGENCE</h1>", unsafe_allow_html=True)
with h_col2:
    coin = st.radio("COIN", ["BTC", "ETH"], horizontal=True, label_visibility="collapsed")

data = fetch_verified_data(coin, st.session_state.period)

if data:
    px, cur_oi, actual_m, magnet_score = data['price'], data['oi'], data['actual'], data['magnet']
    all_pos = data['positions']

    # 코인별 개별 추적 로직 (OI 데이터 검증용)
    prev_oi = st.session_state.oi_history.get(coin, 0)
    prev_px = st.session_state.px_history.get(coin, 0)
    oi_diff = cur_oi - prev_oi if prev_oi > 0 else 0
    px_diff = px - prev_px if prev_px > 0 else 0
    
    st.session_state.oi_history[coin] = cur_oi
    st.session_state.px_history[coin] = px

    # 신호 판별
    sm_signal, sm_color, sm_desc = "INITIALIZING DATA...", "#6b6b7b", "첫 데이터를 수집 중입니다. 잠시만 기다려주세요."
    if prev_oi > 0:
        if abs(oi_diff) < 0.01:
            sm_signal, sm_color, sm_desc = "MARKET CONSOLIDATION", "#6b6b7b", "현재 세력이 힘을 응축하며 관망 중인 구간입니다."
        else:
            if px_diff > 0 and oi_diff > 0: sm_signal, sm_color, sm_desc = "SMART MONEY ACCUMULATING", "var(--green)", "진짜 상승: 세력이 돈 싸들고 롱에 올라타는 중입니다."
            elif px_diff > 0 and oi_diff < 0: sm_signal, sm_color, sm_desc = "SHORT COVERING DETECTED", "var(--orange)", "가짜 상승: 숏 개미들이 손절해서 나오는 반등입니다."
            elif px_diff < 0 and oi_diff > 0: sm_signal, sm_color, sm_desc = "AGGRESSIVE SELLING", "var(--red)", "진짜 하락: 세력이 본격적으로 하락 배팅에 들어갔습니다."
            elif px_diff < 0 and oi_diff < 0: sm_signal, sm_color, sm_desc = "LONG LIQUIDATION EXHAUSTION", "var(--cyan)", "가짜 하락: 롱 개미들 뚝배기 깨지는 중. 하락 끝물입니다."

    # 분석 카드
    a1, a2 = st.columns(2)
    with a1:
        with st.popover(f"❓ 분석 가이드", use_container_width=True):
            st.markdown("### 🎰 판돈(OI)으로 보는 진짜/가짜 구분법\n- **상승+판돈↑**: 고래 매집 (진짜)\n- **상승+판돈↓**: 숏 손절 (가짜)\n- **하락+판돈↑**: 고래 매도 (진짜)\n- **하락+판돈↓**: 롱 청산 (가짜)")
        st.markdown(f"""
            <div class="analysis-card" style="border-top:4px solid {sm_color};">
                <div style="color:var(--dim); font-size:11px;">SMART MONEY FLOW</div>
                <div style="font-size:22px; font-weight:900; color:{sm_color}; margin:10px 0;">{sm_signal}</div>
                <div style="font-size:13px; color:#aaa; line-height:1.4;">{sm_desc}</div>
                <div style="position:absolute; bottom:15px; font-size:11px; color:var(--dim);">
                    Live OI: {cur_oi:,.0f} | Delta: <span style="color:{'var(--green)' if oi_diff>0 else 'var(--red)'}">{oi_diff:+,.2f}</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
    with a2:
        s_tag, s_color = ("CRITICAL", "var(--red)") if magnet_score > 15 else (("WARNING", "var(--orange)") if magnet_score > 8 else ("STABLE", "#6b6b7b"))
        st.markdown(f'<div class="analysis-card" style="border-top:4px solid {s_color};"><div style="color:var(--dim); font-size:11px;">LIQUIDATION MAGNET</div><div style="font-size:32px; font-weight:900; color:{s_color}; margin:10px 0;">${magnet_score:.2f}M</div><div style="margin-top:5px;"><span class="status-tag" style="background:{s_color};">{s_tag}</span></div><div style="position:absolute; bottom:15px; font-size:11px; color:var(--dim);">현재가 근처 잠재적 청산 폭발력</div></div>', unsafe_allow_html=True)

    # 설정 및 시각화 (동일)
    p_list = ["24H", "48H", "3D", "1W", "2W", "1M", "ALL"]
    c1, c2, c3, c4 = st.columns(4)
    with c1: 
        selected_p = st.selectbox("분석 그룹", p_list, index=p_list.index(st.session_state.period))
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
    
    max_v = max([v["L"] + v["S"] for v in ladder.values()] + [1])
    max_d = max([abs(v["S"] - v["L"]) for v in ladder.values()] + [1])
    whales = sorted(all_pos, key=lambda x: x['posVal'], reverse=True)[:15]
    payload = json.dumps({"price": px, "map": ladder, "whales": whales, "maxV": max_v, "maxD": max_d, "coin": coin, "minV": min_val, "tL": sum(p['posVal'] for p in all_pos if p['isLong']), "tS": sum(p['posVal'] for p in all_pos if not p['isLong'])})

    # HTML 렌더링 (사다리)
    html_code = f"""
    <!DOCTYPE html><html><head><link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@600;800&display=swap" rel="stylesheet"><style>
    :root{{--bg:#05050a;--card:#0e0e1a;--ln:#1e1e30;--g:#00ffa3;--r:#ff3e3e;--gold:#ffcc00;--cyan:#00f2ff;--orange:#ff8c00;--dim:#6b6b7b;}}
    body{{background:var(--bg); color:#e1e1e6; font-family:'JetBrains Mono', monospace; margin:0; padding:10px; overflow-x:hidden;}}
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
