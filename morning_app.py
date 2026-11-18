"""출근길 대중교통 — 집(가산동 238-59) → 케이앤웍스 가산오피스, 4가지 루트 중 가장 빨리 도착하는 루트 추천
실행: streamlit run morning_app.py   (Secrets: BUS_API_KEY, KAKAO_JS_KEY 선택)"""
import html as H
import time
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

import bus
import kmap
import morning

KST = ZoneInfo("Asia/Seoul")
st.set_page_config(page_title="출근길 대중교통", page_icon="🌅", layout="wide")

# ── 설정 (정류장/노선은 morning.py 의 CONFIG, 아래는 화면 동작) ────────────
C = morning.CONFIG
REFRESH = 30
WINDOW = (7, 10)          # 평일 이 시간대(시)에만 자동 갱신 (열 때는 항상 1회 조회)
DAILY_LIMIT = 950
FALLBACK = {"금천07": 10, "금천05": 8, "27": 8, "75": 12}   # 실시간 주행시간을 못 구할 때 쓰는 대략값(분)
STOP_FIRST, STOP_SECOND = C["first"]["ars"], C["second_ars"]
COLORS = {"walk": "#6b7280", "a": "#1fa971", "b": "#2f6fed", "c": "#8b5cf6"}

st.markdown("""
<style>
.block-container{padding-top:3.2rem;max-width:1100px}
header[data-testid="stHeader"]{display:none}
[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none}
h1{font-size:1.7rem!important;padding:.2rem 0 .6rem!important}
.hero{background:linear-gradient(135deg,#ff8a2b,#ff5200);color:#fff;border-radius:20px;padding:20px 24px;margin:4px 0 16px;box-shadow:0 6px 18px rgba(255,82,0,.25)}
.hero .hl{font-size:.8rem;font-weight:700;letter-spacing:.08em;opacity:.9}
.hero .ht{font-size:1.15rem;font-weight:700;margin-top:6px}
.hero .big{font-size:2.9rem;font-weight:800;line-height:1.15;margin:6px 0 4px}
.hero .big .sm{font-size:1.1rem;font-weight:600;opacity:.9}
.hero .hs{font-size:.95rem;opacity:.95;line-height:1.5}
.card{border:1px solid rgba(128,128,128,.28);border-radius:18px;padding:16px 18px 10px;background:rgba(128,128,128,.06);margin-bottom:12px}
.card.best{border:2px solid #ff6b00;background:rgba(255,107,0,.07)}
.card .hd{display:flex;align-items:center;gap:8px;font-weight:700;font-size:1.05rem}
.card .tag{margin-left:auto;background:#ff6b00;color:#fff;border-radius:8px;padding:1px 9px;font-size:.75rem;font-weight:700}
.card .big{font-size:2rem;font-weight:800;line-height:1.15;margin:6px 0 2px}
.card .big .sm{font-size:.9rem;font-weight:600;opacity:.7}
.card .gap{opacity:.7;font-size:.85rem;margin-bottom:6px}
.no{width:26px;height:26px;border-radius:50%;color:#fff;display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:.85rem;flex:none}
.stp{display:flex;align-items:flex-start;gap:10px;padding:6px 0;border-top:1px dashed rgba(128,128,128,.28);font-size:.9rem}
.stp .ic{width:22px;text-align:center;flex:none}.stp .tx{flex:1}.stp .rt{font-weight:700;white-space:nowrap}
.stp .sub{opacity:.6;font-size:.78rem}
@media (max-width:640px){.hero{padding:16px}.hero .big{font-size:2.4rem}.card{padding:14px 14px 8px}.stp{font-size:.86rem}}
</style>
""", unsafe_allow_html=True)

try:
    KEY = st.secrets["BUS_API_KEY"]
except Exception:
    st.error("Secrets에 BUS_API_KEY 가 없습니다.")
    st.stop()
try:
    JS_KEY = st.secrets["KAKAO_JS_KEY"]
except Exception:
    JS_KEY = ""

st.title("🌅 출근길 대중교통")

# ── 설정 (체크하면 펼쳐짐, 닫아도 값 유지) ──────────────────────────
ss = st.session_state
vals = ss.setdefault("vals", {})


def S(key, default):
    v = ss.get("s_" + key, vals.get(key, default))
    vals[key] = v
    return v


def setting(key, label, lo, hi, default, step=1):
    ss.setdefault("s_" + key, vals.get(key, default))
    v = st.slider(label, lo, hi, step=step, key="s_" + key)
    vals[key] = v
    return v


if st.checkbox("⚙️ 설정 (출발 시각 · 도보 시간 · 대략 주행시간)", key="show_set"):
    offset = setting("offset", "몇 분 뒤에 집에서 출발할까요? (0 = 지금)", 0, 30, 0)
    walk_all = setting("walk_all", "전구간 도보 시간(분) — 카카오맵 도보 길찾기로 확인해 입력", 5, 90, 40)
    st.caption("아래는 실시간 주행시간을 못 구했을 때만 쓰는 대략값이에요.")
    fb = {r: setting("fb_" + r, f"{r}번 버스 탑승 시간(분)" if r != "금천07" else "금천07 탑승 시간(분)", 2, 40, d)
          for r, d in FALLBACK.items()}
else:
    offset, walk_all = S("offset", 0), S("walk_all", 40)
    fb = {r: S("fb_" + r, d) for r, d in FALLBACK.items()}


# ── 조회 (같은 서버의 접속자가 결과를 공유) ──────────────────────────
@st.cache_resource
def api_counter():
    return {"day": "", "n": 0}


def count_call():
    c, today = api_counter(), datetime.now(KST).strftime("%Y-%m-%d")
    if c["day"] != today:
        c["day"], c["n"] = today, 0
    c["n"] += 1


@st.cache_data(ttl=25, show_spinner=False)
def load(ars):
    count_call()
    arr, stop = bus.fetch_station(ars, KEY)
    return arr, stop, time.time()


@st.cache_data(ttl=120, show_spinner=False)
def load_route(route_id):
    count_call()
    return bus.fetch_route_all(route_id, KEY), time.time()


def is_active():
    now = datetime.now(KST)
    return st.query_params.get("force") == "1" or (WINDOW[0] <= now.hour < WINDOW[1] and now.weekday() < 5)


ROUTE_NAMES = [(STOP_FIRST, C["first"]["route"])] + [(STOP_SECOND, o["route"]) for o in C["options"]]


def fetch_snapshot():
    ss["last_try"] = time.time()
    if api_counter()["n"] >= DAILY_LIMIT:
        ss["snap_err"] = "오늘 조회 한도에 가까워 자동 조회를 멈췄어요."
        return
    try:
        loaded = {a: load(a) for a in (STOP_FIRST, STOP_SECOND)}
    except Exception as e:
        ss["snap_err"] = str(e)
        return
    ss["snap_err"] = ""
    coords, rids = ss.setdefault("coords", {}), ss.setdefault("rids", {})
    for ars, (arr, stop, _) in loaded.items():
        if stop:
            coords[ars] = stop
    for ars, name in ROUTE_NAMES:
        m = bus.pick(loaded[ars][0], name)
        if m and m[0].route_id:
            rids[(ars, name)] = m[0].route_id
    routes = {}
    for rid in set(rids.values()):
        try:
            routes[rid] = load_route(rid)
        except Exception:
            pass
    ss["snap"] = {"t": time.time(), "loaded": loaded, "routes": routes}


def get_snapshot():
    first_visit = "last_try" not in ss                     # 페이지를 처음 연 순간은 시간대와 상관없이 1회 조회
    stale = time.time() - ss.get("last_try", 0) >= REFRESH
    if first_visit or (is_active() and stale):
        fetch_snapshot()
    return ss.get("snap")


def compute():
    snap = get_snapshot()
    if not snap:
        return None
    now = time.time()
    adj = {a: [replace(x, eta_sec=int(x.eta_sec - (now - ts))) for x in arr if x.eta_sec - (now - ts) >= 0]
           for a, (arr, _, ts) in snap["loaded"].items()}
    rids, routes = ss.get("rids", {}), snap["routes"]

    def ride_fn(route, board, off, target):
        fallback = (fb.get(route, 10), "예상")
        ro = routes.get(rids.get((board, route)))
        if not ro:
            return fallback
        items, ts = ro
        got = bus.choose_ride(bus.segment_rides(items, board, off), None if target is None else target + (now - ts))
        return fallback if got is None else (got[0] / 60, "실시간" if got[1] == "bus" else "실시간(구간)")

    trips = morning.plan_all(C, adj[STOP_FIRST], adj[STOP_SECOND], ride_fn, walk_all, offset)
    return dict(now=datetime.now(KST), t=snap["t"], el=now - snap["t"], trips=trips,
                best=morning.best_trip(trips), adj=adj, coords=ss.get("coords", {}))


def mmss(sec):
    sec = int(sec)
    return f"{sec // 60}분 {sec % 60:02d}초"


def step_html(s, hm):
    sub = f'<div class="sub">{H.escape(s.sub)}</div>' if s.sub else ""
    return (f'<div class="stp"><span class="ic">{s.icon}</span><span class="tx">{H.escape(s.text)}{sub}</span>'
            f'<span class="rt">{hm(s.at_sec) if s.at_sec is not None else ""}</span></div>')


@st.fragment(run_every=1)
def main_frag():
    err = ss.get("snap_err")
    if err:
        st.warning(err)
    v = compute()
    if not v:
        return
    now, trips, best = v["now"], v["trips"], v["best"]
    hm = lambda sec: (now + timedelta(seconds=sec)).strftime("%H:%M")
    start = offset * 60
    st.caption(f"{datetime.fromtimestamp(v['t'], KST):%H:%M:%S} 조회 ({int(v['el'])}초 전) · 출발 "
               f"{'지금' if not offset else f'{offset}분 뒤'} 기준 · API {api_counter()['n']}/{DAILY_LIMIT}")

    if best:
        mins = round((best.arrive_sec - start) / 60)
        if best.key == "walk":
            go = "지금 바로 출발해서 끝까지 걸어가세요" if not offset else f"{offset}분 뒤에 출발해서 걸어가세요"
        else:
            li = best.leave_in_sec
            go = (f"{best.steps[1].text.split(' · ')[0]} {mmss(best.first_bus_eta)} 후 도착 · "
                  + ("지금 바로 출발해야 해요!" if li <= 0 else f"늦어도 <b>{mmss(li)}</b> 안에 집에서 출발"))
        st.markdown(
            f'<div class="hero"><div class="hl">가장 빨리 도착하는 루트</div>'
            f'<div class="ht">{H.escape(best.name)}</div>'
            f'<div class="big">{hm(best.arrive_sec)}<span class="sm"> 회사 도착 · 소요 {mins}분</span></div>'
            f'<div class="hs">{go}</div></div>', unsafe_allow_html=True)
    else:
        st.warning("지금은 비교할 수 있는 루트가 없어요.")

    ordered = sorted(trips, key=lambda t: (t.arrive_sec is None, t.arrive_sec or 0))
    cols = st.columns(2)
    for n, tr in enumerate(ordered):
        with cols[n % 2]:
            color = COLORS.get(tr.key, "#555")
            tag = '<span class="tag">추천</span>' if tr is best else ""
            if tr.arrive_sec is None:
                body = f'<div class="gap">⚠️ {H.escape(tr.note)}</div>'
            else:
                gap = "" if tr is best or not best else f'<div class="gap">추천보다 {round((tr.arrive_sec - best.arrive_sec) / 60)}분 늦음</div>'
                body = (f'<div class="big">{hm(tr.arrive_sec)}<span class="sm"> 도착 · 소요 {round((tr.arrive_sec - start) / 60)}분</span></div>'
                        f'{gap}{"".join(step_html(s, hm) for s in tr.steps)}')
            st.markdown(f'<div class="card{" best" if tr is best else ""}"><div class="hd">'
                        f'<span class="no" style="background:{color}">{n + 1}</span><span>{H.escape(tr.name)}</span>{tag}</div>{body}</div>',
                        unsafe_allow_html=True)


@st.fragment(run_every=REFRESH)
def map_frag():
    v = compute()
    if not v or not JS_KEY:
        return
    pts = []
    for ars, route_names, side, color in ((STOP_FIRST, [C["first"]["route"]], "right", "#ff6b00"),
                                          (STOP_SECOND, [o["route"] for o in C["options"]], "left", "#2f6fed")):
        c = v["coords"].get(ars)
        if not c:
            continue
        lines = []
        for name in route_names:
            a = bus.pick(v["adj"][ars], name)[:2]
            lines.append(f"<b>{H.escape(name)}</b> " + (" · ".join("곧" if x.eta_sec < 30 else f"{round(x.eta_sec / 60)}분" for x in a) or "정보 없음"))
        pts.append({"lat": c["lat"], "lng": c["lng"], "best": False, "color": color,
                    "no": "1" if ars == STOP_FIRST else "2", "side": side,
                    "html": "<br>".join(lines) + f'<div style="font-size:11px;color:#777">{H.escape(c["name"])} · {ars}</div>'})
    kmap.show(pts, JS_KEY, height=375)


if not is_active():
    st.caption(f"열 때 한 번 조회했어요 · 자동 갱신은 평일 {WINDOW[0]}~{WINDOW[1]}시에만")
    if st.button("지금 다시 조회"):
        fetch_snapshot()
main_frag()
map_frag()
st.caption("데이터: 서울특별시 버스도착정보(공공데이터포털) · 환승 대기·주행시간은 실시간 데이터로 계산한 추정값이에요")
