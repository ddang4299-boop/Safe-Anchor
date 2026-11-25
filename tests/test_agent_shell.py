"""Unit test lớp vỏ agent: IPC danh sách trắng, mẫu câu cá nhân hóa, logic hiển thị Tray, netguard,
watchdog Tray (không chế độ ẩn), backoff có jitter, bộ đo tỉ lệ chặn trên bộ 50 + 20 tên miền."""
import csv
import json
import random
from pathlib import Path

from agent.domain_rules import CategoryMap, DnsPolicyEngine, DomainSet
from agent.ipc import ALLOWED_OPS, IpcDispatcher
from agent.netguard import build_firewall_commands, complement_ranges
from agent.tray import messages_vi as M
from agent.tray import view_logic as V
from agent.winsys import TrayWatchdog
from agent.ws_client import backoff_delay

ROOT = Path(__file__).resolve().parent.parent


class FakeCore:
    def __init__(self):
        self.idle = None
        self.acked = False

    def report_idle(self, s):
        self.idle = s

    def ack_break(self):
        self.acked = True
        return True


class FakeRuntime:
    def __init__(self):
        self.core = FakeCore()
        self.requests = []

    def ipc_status(self, since):
        return {"phase": "active", "since": since}

    def ipc_request_more_time(self, minutes, reason):
        self.requests.append((minutes, reason))
        return {"sent": True}


# ------------------------------------------------------------------ IPC
def test_ipc_rejects_ops_outside_whitelist():
    d = IpcDispatcher(FakeRuntime())
    for op in ("disable_filter", "set_policy", "stop_service", "add_time", "unlock", "__class__"):
        assert d.handle({"op": op}) == {"ok": False, "error": "not_allowed"}
    assert "add_time" not in ALLOWED_OPS and "set_policy" not in ALLOWED_OPS


def test_ipc_validates_arguments():
    rt = FakeRuntime()
    d = IpcDispatcher(rt)
    assert d.handle({"op": "request_more_time", "args": {"minutes": 999}})["error"] == "bad_args"
    assert d.handle({"op": "request_more_time", "args": {"minutes": 15, "reason": "x" * 201}})["error"] == "bad_args"
    assert d.handle({"op": "request_more_time", "args": {"minutes": 30, "reason": "làm bài"}})["ok"]
    assert rt.requests == [(30, "làm bài")]
    assert d.handle({"op": "report_idle", "args": {"seconds": -5}})["error"] == "bad_args"
    assert d.handle({"op": "report_idle", "args": {"seconds": 400}})["ok"] and rt.core.idle == 400
    assert json.loads(d.handle_raw(b"\xff\xfe garbage"))["error"] == "bad_json"


# ------------------------------------------------------------------ mẫu câu
PROFILE = {"nickname": "Bin", "self_pronoun": "con", "guardian_call": "Mẹ", "age_mode": "choi"}


def test_message_templates_insert_names_and_capitalize():
    rnd = random.Random(1)
    t = M.render("request_approved", PROFILE, phut=15, loi_nhan="Nhớ nghỉ mắt nha", rnd=rnd)
    assert "Mẹ" in t and "Bin" in t and "Nhớ nghỉ mắt nha" in t
    t2 = M.render("warn_5", {**PROFILE, "nickname": "na"}, rnd=random.Random(0))
    assert t2[0].isupper()  # tên đứng đầu câu vẫn viết hoa


def test_no_forbidden_words_in_any_template():
    for situation, variants in M.MESSAGES.items():
        for _, text in variants:
            low = text.lower()
            assert not any(w in low for w in M.FORBIDDEN_WORDS), (situation, text)


def test_every_situation_has_variant_for_both_age_modes():
    for situation in M.MESSAGES:
        for mode in ("mam", "choi"):
            assert M.render(situation, {**PROFILE, "age_mode": mode})


# ------------------------------------------------------------------ logic hiển thị
def test_time_bar_color_thresholds():
    assert V.time_color(30 * 60) == V.MINT
    assert V.time_color(10 * 60) == V.SUN
    assert V.time_color(60) == V.CORAL
    assert V.time_mood(60) != V.time_mood(30 * 60)  # không chỉ dùng màu


def test_block_screen_answers_three_questions():
    st = {"phase": "locked", "lock_reason": "schedule", "next_allowed": "16:00", "profile": PROFILE}
    s = V.block_screen(st)
    assert s.what and s.why and s.next_steps and "16:00" in s.why
    g = V.block_screen({"phase": "grace", "lock_reason": "quota", "grace_left": 42, "profile": PROFILE})
    assert g.countdown == 42 and g.can_ack_break
    assert V.block_screen({"phase": "active", "profile": PROFILE}) is None


# ------------------------------------------------------------------ netguard & watchdog & backoff
def test_complement_ranges_excludes_upstreams():
    r = complement_ranges(["8.8.8.8", "1.1.1.1"])
    assert r == ["0.0.0.1-1.1.1.0", "1.1.1.2-8.8.8.7", "8.8.8.9-255.255.255.254"]
    cmds = [" ".join(c) for c in build_firewall_commands(["8.8.8.8"])]
    assert any("remoteport=853" in c for c in cmds)
    assert any("remoteport=53" in c and "8.8.8.9-" in c for c in cmds)


def test_tray_watchdog_relaunches_then_suspends():
    w = TrayWatchdog()
    w.contact(0)
    assert w.decide(10, True) == "ok"
    assert w.decide(100, True) == "launch"  # trẻ kill Tray => mở lại, KHÔNG dừng kiểm soát
    for i in range(TrayWatchdog.MAX_FAILS):
        w.launch_result(False, 100 + i)
    assert w.decide(200, True) == "suspend"  # không thể hiện biểu tượng => tự dừng (không chế độ ẩn)
    assert w.decide(200, False) == "ok"


def test_backoff_with_jitter_bounds():
    rnd = random.Random(7)
    delays = [backoff_delay(a, rnd) for a in range(10)]
    assert 0.5 <= delays[0] <= 1.0
    assert all(d <= 30 for d in delays) and delays[-1] >= 15


# ------------------------------------------------------------------ tỉ lệ chặn trên bộ dữ liệu đề
def test_block_rate_on_test_domains():
    cats = {r["domain"]: r["category"] for r in csv.DictReader(open(ROOT / "data/categories.csv", encoding="utf-8"))}
    engine = DnsPolicyEngine(categories=CategoryMap(cats), blocked_categories=frozenset({"social", "inappropriate"}))
    rows = list(csv.DictReader(open(ROOT / "data/test_domains.csv", encoding="utf-8")))
    should_block = [r["domain"] for r in rows if r["expected"] == "block"]
    edu = [r["domain"] for r in rows if r["group"] == "education"]
    blocked = sum(engine.decide(d).action == "block" for d in should_block)
    false_pos = [d for d in edu if engine.decide(d).action == "block"]
    assert len(should_block) == 50 and len(edu) == 20
    assert blocked / len(should_block) >= 0.95
    assert false_pos == []


def test_tray_view_logic_for_new_ui():
    # thanh thời gian đổi màu MƯỢT: Mint (>= 20 phút) -> Vàng nắng (10 phút) -> Cam ấm (0)
    assert V.smooth_time_color(30 * 60) == V.MINT
    assert V.smooth_time_color(10 * 60) == V.SUN
    assert V.smooth_time_color(0) == V.ORANGE
    assert V.smooth_time_color(15 * 60) not in (V.MINT, V.SUN, V.ORANGE)  # màu trung gian
    # chip lý do xin giờ: đúng xưng hô, không vượt giới hạn 200 ký tự của IPC
    rs = V.quick_reasons({"self_pronoun": "em"})
    assert len(rs) == 3 and rs[0].startswith("Em") and all(len(r) <= 200 for r in rs)
    # Bento "Hôm nay": học tập / giải trí (trò chơi + giải trí) / huy hiệu đúng giờ
    t = V.today_tiles({"used_sec": 3600, "quota_min": 90, "phase": "active"},
                      {"cats_today": {"education": 30, "games": 10, "entertainment": 5}})
    assert (t["study"], t["fun"], t["on_time"]) == (30, 15, True)
    assert not V.today_tiles({"used_sec": 100 * 60, "quota_min": 90}, None)["on_time"]
    # "Tạm nghỉ 2h": màn chặn báo trước giờ mở lại; hết giờ nghỉ có lời báo dịu dàng
    s = V.block_screen({"phase": "locked", "lock_reason": "parent", "lock_until": "16:30", "profile": {}})
    assert "16:30" in s.what
    assert V.toast_text({"kind": "break_over"}, {"nickname": "Bin", "guardian_call": "Mẹ"})


def test_mascot_lines_use_real_numbers_and_stay_kind():
    from datetime import datetime
    prof = {"nickname": "Bin", "self_pronoun": "con", "guardian_call": "Mẹ"}
    now = datetime(2026, 11, 20, 16, 5)
    tic = V.mascot_lines("tictac", prof, 23 * 60, "active", now=now)
    assert any("còn 23 phút" in s for s in tic["poke"]) and any("16:05" in s for s in tic["poke"])
    assert any("Còn 8 phút" in s for s in V.mascot_lines("tictac", prof, 8 * 60, "active")["poke"])
    assert all("tạm nghỉ" in s or "Ngủ ngon" in s for s in V.mascot_lines("tictac", prof, 0, "locked")["poke"])
    assert any("học 35 phút" in s for s in V.mascot_lines("sao", prof, study_min=35)["poke"])
    assert any("hỏi Mẹ" in s for s in V.mascot_lines("khien", prof)["poke"])
    allx = V.mascot_lines("khien", {}) | {"x": V.mascot_lines("sao", None)["poke"]}
    assert all("bạn" in s for s in allx["party"] + allx["hint"])   # thiếu hồ sơ => gọi "bạn", không lỗi
    # mascot không bao giờ nhắc chuyện bị chặn (trẻ không có cảm giác bị theo dõi)
    for k in ("tictac", "khien", "sao"):
        for pool in V.mascot_lines(k, prof, 5 * 60, "active", 10).values():
            assert all("chặn" not in s.lower() for s in pool)
    assert set(V.MOOD_TO_EXPR) >= {"happy", "encourage", "remind", "sleepy", "celebrate"}


def test_tray_mascot3d_atlas_and_interactions(monkeypatch, tmp_path):
    import math
    import os
    import pytest
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    from agent.tray import app as A
    from agent.tray import mascot3d as M3
    _qa = QApplication.instance() or QApplication([])  # noqa: F841
    # atlas render sẵn: đủ 3 nhân vật, siêu dữ liệu khớp ảnh
    for k in M3.KINDS:
        meta = json.loads((M3.ATLAS_DIR / f"{k}.json").read_text(encoding="utf-8"))
        assert meta["yaw_frames"] == 24 and set(meta["exprs"]) == {"joy", "blink", "sleepy", "wow", "love"}
        at = M3.Atlas.get(k)
        assert at is not None and len(at.frames) == 29 and 0 < at.head < at.feet < 1
    at = M3.Atlas.get("tictac")
    assert at.frame_index(0, "happy") == 0 and at.frame_index(0, "joy") == at.exprs["joy"]
    assert at.frame_index(math.pi, "joy") == 12            # quay lưng: khung xoay, không phải khung nét mặt
    assert at.frame_index(-math.pi / 12, "happy") == 23    # quay trái 15° = khung cuối
    # trong cửa sổ: chạm => nét mặt vui + bong bóng thoại dùng lời thoại thật; 5 chạm => nhảy múa
    host = QWidget()
    m = A.live_mascot("tictac", "happy", 128)
    assert isinstance(m, M3.Mascot3D)
    QVBoxLayout(host).addWidget(m)
    m.set_context(profile={"nickname": "Bin"}, remaining_sec=600 + 1, phase="active")
    events = []
    m.reacted.connect(events.append)
    m.poke()
    assert m._expr() == "joy" and m.bubble is not None
    pool = V.mascot_lines("tictac", {"nickname": "Bin"}, 601, "active")["poke"]
    assert m.bubble.text in pool or m.bubble.text.startswith("Bây giờ là")   # câu giờ có thể lệch phút khi chạy test
    for _ in range(4):
        m.poke()
    assert events == ["poke"] * 4 + ["party"]
    m.tickle()
    assert events[-1] == "tickle" and m._expr() == "love"
    m.set("sao", "celebrate")
    assert m.kind == "sao" and m._expr() == "love"         # nét mặt tạm thời vẫn giữ tới khi hết hạn
    # giảm chuyển động: không nhảy / không xoay, vẫn đổi nét mặt
    r = M3.Mascot3D("khien", "happy", 96, reduced=True)
    r.poke()
    for _ in range(20):
        r._step(1 / 60)
    assert r.jump_px == 0 and r.spinT < 0 and r._expr() == "joy"
    # thiếu ảnh atlas => Tray vẫn chạy với mascot SVG
    monkeypatch.setattr(M3, "ATLAS_DIR", tmp_path)
    monkeypatch.setattr(M3.Atlas, "_cache", {})
    assert isinstance(A.live_mascot("sao", "happy", 96), A.Mascot)


def test_child_app_view_helpers():
    from datetime import datetime
    prof = {"nickname": "Bin", "self_pronoun": "con", "guardian_call": "Mẹ"}
    assert V.greeting(prof, datetime(2026, 11, 20, 9, 0)) == "Chào Bin! Hôm nay là Thứ Sáu, 20/11"
    assert V.greeting(None, datetime(2026, 11, 22, 9, 0)).startswith("Chào bạn! Hôm nay là Chủ Nhật")
    # Tầng 1: MỘT thông điệp (còn bao lâu); thanh đo phần ĐÃ dùng trên hạn mức
    st = {"remaining_sec": 100 * 60, "used_sec": 20 * 60, "quota_min": 120, "phase": "active"}
    h = V.hero_time(st)
    assert (h["eyebrow"], h["big"], h["ratio_text"]) == ("CÒN LẠI HÔM NAY", "1 giờ 40 phút", "Đã dùng 20 / 120 phút")
    assert abs(h["ratio"] - 20 / 120) < 1e-9 and not h["low"] and not h["locked"]
    # khung giờ hết TRƯỚC hạn mức => nói rõ, để hai con số không "lệch" khó hiểu
    assert V.hero_time({**st, "remaining_sec": 30 * 60})["eyebrow"] == "CÒN LẠI TRONG KHUNG GIỜ NÀY"
    assert V.hero_time({**st, "remaining_sec": 9 * 60})["low"]
    lk = V.hero_time({**st, "phase": "locked", "remaining_sec": 0, "lock_until": "16:30"})
    assert lk["locked"] and lk["eyebrow"] == "TẠM NGHỈ ĐẾN 16:30" and not lk["low"]
    assert V.hero_time({"quota_min": 0})["ratio"] == 1.0                      # không chia cho 0
    # trạng thái yêu cầu: lấy yêu cầu MỚI NHẤT, dùng đúng tên gọi người giám hộ
    assert V.request_status({}, prof) is None
    assert V.request_status({"requests": [{"status": "denied"}, {"status": "approved"}]}, prof) == \
        ("approved", "✓ Mẹ đã đồng ý thêm giờ")
    assert V.request_status({"requests": [{"status": "pending"}]}, {})[1] == "Đã gửi — Ba Mẹ đang xem…"
    # Góc Học Tập: không ghi "không giới hạn" trơn (học vẫn tính vào giờ cả ngày)
    assert V.study_note(16) == "Không giới hạn riêng — Cố lên nhé!" and "Sao Nhỏ" in V.study_note(0)
    # Góc Giải Trí: có ngân sách => "đã dùng / giới hạn" + thanh; không có => chỉ số phút, không vẽ thanh
    f = V.fun_card({"budgets": {"games": {"used_min": 12.4, "limit_min": 45}}}, None)
    assert (f["big"], f["ratio"], f["note"]) == ("12 / 45 phút", 12 / 45, "Còn 33 phút trò chơi hôm nay")
    full = V.fun_card({"budgets": {"games": {"used_min": 45, "limit_min": 45}}}, None)
    assert full["ratio"] == 1.0 and full["note"].startswith("Hết giờ trò chơi")
    nob = V.fun_card({}, {"cats_today": {"games": 3, "entertainment": 4, "education": 50}})
    assert (nob["big"], nob["ratio"]) == ("7 phút", None)
    # kim "bây giờ": phút thật từ agent; bản agent cũ chỉ có ô 30 phút => giữa ô
    assert V.now_minute({"now_min": 14 * 60 + 21}) == 861 and V.now_minute({"now_slot": 4}) == 135
    assert V.now_minute({"now_min": 5000}) == 1439


def test_child_app_explore_and_audit_rows():
    today = {"top_apps": [{"name": "scratch.exe", "display": "Scratch 3", "minutes": 40},
                          {"name": "mspaint.exe", "minutes": 0}, {"name": ""}],
             "top_domains": [{"name": "example.org", "count": 8}, {"name": "school.example", "count": 2}]}
    r = V.explore_rows(today)
    assert [a["title"] for a in r["apps"]][0] == "Scratch 3" and len(r["apps"]) == 2   # bỏ dòng thiếu tên
    assert r["apps"][0]["ratio"] == 1.0 and r["apps"][1]["value"] == "dưới 1 phút"
    assert [d["value"] for d in r["domains"]] == ["8 lần ghé", "2 lần ghé"] and r["domains"][1]["ratio"] == 0.25
    assert r["domains"][0]["colors"] == V.avatar_colors("EXAMPLE.ORG")              # màu ổn định theo tên
    assert V.explore_rows(None) == {"apps": [], "domains": []}
    prof = {"nickname": "Bin", "guardian_call": "Mẹ"}
    chat = V.audit_chat([{"when": "hôm nay, 19:50", "lines": ["Mẹ đã đồng ý cho thêm 15 phút",
                                                               "Con đã xin thêm 15 phút"]},
                         {"when": "17/11, 08:02", "lines": ["Mẹ đã đổi chặn trang adult-sim-01.test-block.example"]}],
                        prof)
    assert chat[0] == {"stamp": "19:50 hôm nay", "text": "Mẹ đã đồng ý tặng thêm 15 phút cho Bin",
                       "who": "guardian", "kind": "gift", "initial": "M"}
    assert (chat[1]["who"], chat[1]["kind"], chat[1]["initial"]) == ("child", "ask", "B")
    assert chat[2]["stamp"] == "08:02 17/11" and chat[2]["kind"] == "edit"


def test_child_app_window_and_hud(monkeypatch):
    import os
    import pytest
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from agent.tray import app as A
    from agent.tray import ui_kit as K
    _qa = QApplication.instance() or QApplication([])  # noqa: F841
    monkeypatch.setattr(A, "reduced_motion", lambda: True)       # hoạt ảnh tức thì => kiểm tra đồng bộ
    w = A.MainWindow(A.Bridge(None, 0, demo=True), lambda: None)
    assert w.windowFlags() & A.Qt.FramelessWindowHint           # không còn thanh tiêu đề đen của hệ điều hành
    w._profile = A.DEMO_PROFILE
    w.update_today(A.demo_status(0))
    assert w.t_big.text() == "1 giờ 40 phút" and w.t_ratio.text() == "Đã dùng 20 / 120 phút"
    assert not w.t_req.isHidden() and "Mẹ đã đồng ý" in w.t_req.text()
    assert w.t_study.text() == "16 phút" and w.t_fun.text() == "0 / 45 phút"
    assert w.t_badge_icon.sparkle and w.t_medal is not None
    w.update_today(A.demo_status(0, request=""))
    assert w.t_req.isHidden()
    # điều hướng: 4 mục, đúng một mục được chọn; mở tab thì nạp dữ liệu thật của tab
    for i in range(4):
        w.go(i)
        assert w.stack.currentIndex() == i and w.nav_group.checkedId() == i
    w.go(1)
    assert w.e_apps.count() == 5 and w.e_doms.count() == 5
    assert all(isinstance(w.e_apps.itemAt(k).widget(), A.ExploreRow) for k in range(5))
    w.go(2)
    assert w.a_list.lay.count() == 4                               # mỗi dòng nhật ký = một bong bóng
    # mỗi thẻ được đúng MỘT "chủ bóng" vẽ bóng (không vẽ 2 lần, không bỏ sót)
    cards = w.findChildren(K.Card)
    assert cards and all(K._host_of(c) is not None for c in cards)
    # viên HUD: rê chuột => mở rộng và hiện 2 nút; rời chuột => thu lại
    pill = A.Pill()
    pill.update_status(A.demo_status(0))
    assert pill.label.text().endswith("1 giờ 40 phút") and pill.sub.text() == "còn lại"
    got = []
    pill.request.connect(lambda: got.append("req"))
    pill.enterEvent(None)
    assert pill.expanded() and pill.actions.isVisibleTo(pill)
    pill.req_btn.click()
    assert got == ["req"]
    pill._animate(0.0)
    assert not pill.expanded() and not pill.actions.isVisibleTo(pill)
    pill.update_status({**A.demo_status(0, "locked", 0), "lock_until": "16:30"})
    assert pill.sub.text() == "đến 16:30"
