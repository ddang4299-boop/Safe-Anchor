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
    assert V.time_icon(60) != V.time_icon(30 * 60)  # không chỉ dùng màu


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
