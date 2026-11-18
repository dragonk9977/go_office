"""출근길 루트 비교 로직 (Streamlit 비의존)
집 → [도보] → 18772 금천07 승차 → 18511 하차 → [도보] → 18644 환승(금천05 / 27 / 75) → 하차 → [도보] → 회사
+ 전구간 도보 루트.  모든 시각은 '지금'을 0으로 한 초 단위."""
from dataclasses import dataclass, field

import bus

CONFIG = dict(
    first=dict(route="금천07", ars="18772", off="18511", walk_min=5),
    walk2_min=6,                       # 18511 하차 → 18644 도보
    options=[
        dict(key="a", name="금천07 → 금천05", route="금천05", off="18500", walk_end_min=1),
        dict(key="b", name="금천07 → 27번", route="27", off="18810", walk_end_min=2),
        dict(key="c", name="금천07 → 75번", route="75", off="18995", walk_end_min=8),
    ],
    second_ars="18644",
)


@dataclass
class Step:
    icon: str
    text: str
    at_sec: float | None = None   # 이 단계가 끝나는(또는 탑승하는) 시각
    sub: str = ""


@dataclass
class Trip:
    key: str
    name: str
    arrive_sec: float | None = None
    leave_in_sec: float | None = None   # 늦어도 이때까지 집에서 출발해야 첫 버스를 탐 (걷기만 하면 None)
    first_bus_eta: float | None = None
    steps: list = field(default_factory=list)
    note: str = ""


def plan_all(c, arr_first, arr_second, ride_fn, walk_all_min, offset_min=0):
    """c: {first, walk2_min, options, second_ars} / arr_*: 지금 기준으로 보정된 도착목록
    ride_fn(route, board_ars, off_ars, target_eta|None) -> (분, 출처)"""
    start = offset_min * 60
    trips = []
    t = start + walk_all_min * 60
    trips.append(Trip("walk", "전구간 도보", arrive_sec=t,
                      steps=[Step("🚶", f"도보 {walk_all_min}분", t)]))

    f = c["first"]
    reach1 = start + f["walk_min"] * 60
    b1 = bus.next_transfer(bus.pick(arr_first, f["route"]), reach1)
    for o in c["options"]:
        tr = Trip(o["key"], o["name"])
        trips.append(tr)
        if b1 is None:
            tr.note = f"{f['route']} 도착 정보가 없어요"
            continue
        ride1, src1 = ride_fn(f["route"], f["ars"], f["off"], None if b1.estimated else b1.eta_sec)
        off1 = b1.eta_sec + ride1 * 60
        reach2 = off1 + c["walk2_min"] * 60
        b2 = bus.next_transfer(bus.pick(arr_second, o["route"]), reach2)
        if b2 is None:
            tr.note = f"{o['route']} 도착 정보가 없어요"
            continue
        ride2, src2 = ride_fn(o["route"], c["second_ars"], o["off"], None if b2.estimated else b2.eta_sec)
        off2 = b2.eta_sec + ride2 * 60
        arrive = off2 + o["walk_end_min"] * 60
        e1 = " (추정)" if b1.estimated else ""
        e2 = " (추정)" if b2.estimated else ""
        tr.arrive_sec, tr.first_bus_eta = arrive, b1.eta_sec
        tr.leave_in_sec = b1.eta_sec - f["walk_min"] * 60
        tr.steps = [
            Step("🚶", f"도보 {f['walk_min']}분 → {f['ars']} 정류장", reach1),
            Step("🚌", f"{f['route']} 승차 · 대기 {int(b1.eta_sec - reach1) // 60}분{e1}", b1.eta_sec),
            Step("🚏", f"{f['off']} 하차", off1, f"주행 {ride1:.0f}분 · {src1}"),
            Step("🚶", f"도보 {c['walk2_min']}분 → {c['second_ars']} 정류장", reach2),
            Step("🚌", f"{o['route']} 승차 · 대기 {int(b2.eta_sec - reach2) // 60}분{e2}", b2.eta_sec),
            Step("🚏", f"{o['off']} 하차", off2, f"주행 {ride2:.0f}분 · {src2}"),
            Step("🏢", f"도보 {o['walk_end_min']}분 → 회사 도착", arrive),
        ]
    return trips


def best_trip(trips):
    """대중교통 루트 중 가장 빨리 도착하는 루트 (전구간 도보는 비교용이라 제외)"""
    ok = [t for t in trips if t.arrive_sec is not None and t.key != "walk"]
    return min(ok, key=lambda t: t.arrive_sec) if ok else None
