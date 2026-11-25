"""Unit test F1: lịch 7×48, quota thường/cuối tuần, đếm thực, cảnh báo 10/5/1, ân hạn, chống chỉnh giờ."""
from agent import schedule as sch
from agent.clock import TrustedClock
from agent.core import AgentCore, DEFAULT_POLICY
from tests.fakes import FakeClock, vn

ALL_DAY = "1" * 336


def make_core(wall_dt, quota=3, weekend=None, schedule=ALL_DAY, budgets=None, synced=True):
    fc = FakeClock(wall_dt)
    clock = TrustedClock(mono=fc.mono, wall=fc.wall)
    if synced:
        clock.sync_cristian(fc.wall(), fc.mono(), fc.mono())
    pol = {**DEFAULT_POLICY, "quota": {"weekday_min": quota, "weekend_min": weekend if weekend is not None else quota},
           "schedule": schedule, "category_budgets": budgets or {}}
    core = AgentCore(clock, pol)
    core.tick()  # tick đầu chỉ đặt mốc monotonic (dt = 0)
    return fc, core


def run(fc, core, seconds):
    acts = []
    for _ in range(int(seconds)):
        fc.advance(1)
        acts += core.tick()
    return acts


def events(acts, etype=None):
    return [a.data for a in acts if a.kind == "event" and (etype is None or a.data["type"] == etype)]


# ---------------- lịch ----------------
def test_slot_index_and_schedule_string():
    assert sch.slot_index(vn(2026, 11, 16, 0, 0)) == 0  # Thứ Hai 00:00
    assert sch.slot_index(vn(2026, 11, 16, 13, 45)) == 27
    assert sch.slot_index(vn(2026, 11, 22, 23, 59)) == 335  # Chủ Nhật 23:30
    s = sch.daily_window("06:00", "21:00")
    assert sch.validate(s) and len(s) == 336
    assert sch.is_allowed(s, vn(2026, 11, 16, 6, 0)) and not sch.is_allowed(s, vn(2026, 11, 16, 21, 0))
    assert not sch.validate("1" * 335) and not sch.validate("2" * 336)


def test_seconds_until_block_and_next_allowed():
    s = sch.daily_window("06:00", "21:00")
    assert sch.seconds_until_block(s, vn(2026, 11, 16, 20, 50)) == 600
    assert sch.next_allowed_start(s, vn(2026, 11, 16, 22, 10)).hour == 6


# ---------------- quota ----------------
def test_quota_3_minutes_locks_on_time():
    fc, core = make_core(vn(2026, 11, 18, 10))  # Thứ Tư
    acts = run(fc, core, 180)
    assert core.phase == "grace"  # hết đúng 3 phút -> vào ân hạn
    acts += run(fc, core, 60)
    assert core.phase == "locked"
    assert any(a.kind == "lock_session" for a in acts)
    assert events(acts, "locked")[0]["subject"] == "quota"


def test_weekday_vs_weekend_quota():
    _, core_wd = make_core(vn(2026, 11, 18), quota=60, weekend=150)
    _, core_we = make_core(vn(2026, 11, 21), quota=60, weekend=150)  # Thứ Bảy
    core_wd.tick(); core_we.tick()
    assert core_wd.status()["quota_min"] == 60
    assert core_we.status()["quota_min"] == 150


def test_warnings_10_5_1_each_exactly_once():
    fc, core = make_core(vn(2026, 11, 18), quota=15)
    acts = run(fc, core, 15 * 60)
    warns = [int(n.data["minutes"]) for n in acts if n.kind == "notify" and n.data["kind"] == "warn"]
    assert warns == [10, 5, 1]
    assert len(events(acts, "quota_warning")) == 3


def test_not_counted_when_locked_or_idle():
    fc, core = make_core(vn(2026, 11, 18), quota=60)
    run(fc, core, 60)
    core.set_session_locked(True)
    run(fc, core, 120)
    core.set_session_locked(False)
    core.report_idle(301)  # Tray báo rảnh hơn 5 phút
    run(fc, core, 120)
    core.report_idle(0)
    run(fc, core, 60)
    assert abs(core.used_sec - 120) <= 1  # chỉ 60 + 60 giây có người dùng thật


def test_sleep_gap_is_capped():
    fc, core = make_core(vn(2026, 11, 18), quota=60)
    core.tick()
    fc.advance(3600)  # máy ngủ 1 giờ giữa hai tick
    core.tick()
    assert core.used_sec <= 5


# ---------------- chống chỉnh đồng hồ ----------------
def test_clock_rollback_3h_does_not_increase_quota():
    fc, core = make_core(vn(2026, 11, 18, 20), quota=30)
    run(fc, core, 600)
    used_before, day_before = core.used_sec, core.day
    fc.set_wall_offset(-3 * 3600)  # trẻ lùi đồng hồ 3 giờ
    acts = run(fc, core, 5)
    assert core.used_sec >= used_before  # không bị reset
    assert core.day == day_before
    assert any(a.kind == "integrity" and a.data["delta_sec"] < -10000 for a in acts)


def test_clock_forward_to_tomorrow_does_not_reset_day_when_synced():
    fc, core = make_core(vn(2026, 11, 18, 20), quota=30)
    run(fc, core, 300)
    fc.set_wall_offset(+86400)  # tua sang ngày mai để mong được reset quota
    run(fc, core, 3)
    assert core.day == "2026-11-18" and core.used_sec >= 300


def test_cristian_sync_uses_half_rtt():
    fc = FakeClock(vn(2026, 11, 18))
    clock = TrustedClock(mono=fc.mono, wall=fc.wall)
    t0 = fc.mono()
    fc.advance(0.2)  # RTT 200 ms
    clock.sync_cristian(server_time=5000.0, t0_mono=t0, t1_mono=fc.mono())
    assert abs(clock.now() - 5000.1) < 1e-6
    fc.advance(10)
    assert abs(clock.now() - 5010.1) < 1e-6


def test_restart_after_rollback_keeps_usage():
    fc, core = make_core(vn(2026, 11, 18, 20), quota=30)
    run(fc, core, 600)
    snap = core.snapshot()
    # khởi động lại máy khi offline, đồng hồ đã bị lùi 1 ngày
    fc2 = FakeClock(vn(2026, 11, 17, 20))
    clock2 = TrustedClock(mono=fc2.mono, wall=fc2.wall)
    core2 = AgentCore(clock2, core.policy)
    core2.restore(snap)
    core2.tick()
    assert core2.day == "2026-11-18" and core2.used_sec >= 600


# ---------------- lịch & lệnh khẩn ----------------
def test_outside_schedule_starts_lock_flow_within_5s():
    fc, core = make_core(vn(2026, 11, 18, 21, 0), quota=120, schedule=sch.daily_window("06:00", "21:00"))
    # Ngay tick ĐẦU TIÊN (≤ 1 giây) đã vào quy trình khóa: thông báo + đếm ngược ân hạn.
    assert core.phase == "grace" and core.lock_reason == "schedule"
    assert any(n["kind"] == "grace" for n in core.status()["notifications"])
    run(fc, core, 60)
    assert core.phase == "locked"


def test_lock_now_and_unlock():
    fc, core = make_core(vn(2026, 11, 18), quota=120)
    core.tick()
    acts = core.apply_command("lock_now", {"by": "Mẹ"})
    assert core.phase == "locked" and core.lock_reason == "parent"
    assert events(acts, "locked")[0]["subject"] == "parent"
    core.apply_command("unlock", {"minutes": 0})
    assert core.phase == "active"


def test_add_time_extends_and_rearms_warnings():
    fc, core = make_core(vn(2026, 11, 18), quota=3)
    run(fc, core, 200)
    assert core.phase == "grace"
    acts = core.apply_command("add_time", {"minutes": 15})
    assert core.phase == "active"
    assert events(acts, "override_granted")[0]["duration_sec"] == 900
    assert 10 not in core.warned  # sẽ cảnh báo lại khi còn 10 phút


def test_add_time_outside_schedule_actually_unlocks():
    """Lỗi thật: 23:05, lịch 06:00–22:00, ba mẹ đồng ý +15 phút mà máy vẫn "Tạm nghỉ" (chỉ quota được cộng)."""
    fc, core = make_core(vn(2026, 11, 25, 23, 5), quota=90, schedule=sch.daily_window("06:00", "22:00"))
    run(fc, core, 70)
    assert core.phase == "locked" and core.lock_reason == "schedule"
    acts = core.apply_command("add_time", {"minutes": 15})
    assert core.phase == "active" and 899 <= core.remaining_sec <= 900
    assert any(a.kind == "unlock_session" for a in acts)
    core.apply_command("add_time", {"minutes": 10})       # duyệt thêm lần nữa => nối tiếp, không ghi đè
    assert 1499 <= core.remaining_sec <= 1500
    run(fc, core, 25 * 60 + 61)                            # hết phần được thêm + 60 giây ân hạn => nghỉ lại
    assert core.phase == "locked" and core.lock_reason == "schedule"


def test_add_time_inside_schedule_only_raises_quota():
    fc, core = make_core(vn(2026, 11, 18, 10), quota=3, schedule=sch.daily_window("06:00", "22:00"))
    run(fc, core, 200)
    core.apply_command("add_time", {"minutes": 15})
    assert core.override_until is None and core.phase == "active"


def test_ack_break_locks_with_self_subject():
    fc, core = make_core(vn(2026, 11, 18), quota=1)
    run(fc, core, 61)
    assert core.ack_break()
    acts = run(fc, core, 1)
    assert core.phase == "locked" and events(acts, "locked")[0]["subject"] == "self"


def test_category_budget_independent_counters():
    fc, core = make_core(vn(2026, 11, 18), quota=120, budgets={"games": 1})
    core.set_running_categories({"games"})
    acts = run(fc, core, 61)
    assert "games" in core.exhausted and core.phase == "active"
    assert any(a.kind == "budgets_changed" for a in acts)
    core.set_running_categories({"education"})
    run(fc, core, 30)
    assert round(core.used_by_cat["games"]) == 61 and round(core.used_by_cat["education"]) == 30
    assert round(core.used_sec) == 91


def test_stale_policy_falls_back_to_default_time_limits():
    fc, core = make_core(vn(2026, 11, 18, 10), quota=5)
    core.server_contact()
    fc.advance(8 * 86400)  # mất kết nối 8 ngày (> N = 7)
    core.tick()
    assert core.is_stale()
    assert core.status()["quota_min"] == 120  # fail-open có giới hạn
    assert core.time_policy()["dns"] == core.policy["dns"]  # lọc web vẫn giữ (fail-closed)


def test_timed_break_unlocks_itself_and_survives_restart():
    """'Tạm nghỉ 2h': hết hạn agent TỰ mở (không cần mạng); mốc hết hạn nằm trong snapshot."""
    fc, core = make_core(vn(2026, 11, 18), quota=600)
    core.apply_command("lock_now", {"by": "Mẹ", "minutes": 120})
    assert core.phase == "locked" and core.status()["lock_until"] == "12:00"
    for _ in range(6):  # 1 giờ sau: vẫn tạm nghỉ
        fc.advance(600)
        core.tick()
    assert core.phase == "locked"
    assert core.snapshot()["parent_lock_until"] is not None
    for _ in range(7):  # quá mốc 2 giờ
        fc.advance(600)
        core.tick()
    assert core.phase == "active" and not core.parent_lock and core.status()["lock_until"] is None
    assert any(n["kind"] == "break_over" for n in core.status()["notifications"])
