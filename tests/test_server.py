"""Tích hợp server (FastAPI TestClient): xác thực, CSRF, IDOR, ghép đôi -> heartbeat -> chính sách,
sự kiện idempotent, xoay vòng refresh token, lệnh khẩn áp dụng đúng một lần."""
import re
import time
import uuid

import pytest

from agent.clock import TrustedClock
from agent.core import AgentCore
from agent.local_cache import LocalCache
from agent.policy_verify import PolicyVerifier, canonical_json as agent_canon
from server.security import FieldCipher, hash_password, verify_password
from server.signing import canonical_json as server_canon
from tests.conftest import login, make_parent


def new_code(client, csrf, child_id):
    r = client.post(f"/children/{child_id}/pairing-code", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    assert r.status_code == 200
    return re.search(r'class="pair-code"[^>]*>([A-Z0-9-]{9})<', r.text).group(1)


def enroll(client, code, fp="f" * 64):
    r = client.post("/api/enroll", json={"code": code, "fingerprint": fp, "hostname": "PC-test"})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


# ------------------------------------------------------------------ mật mã cơ bản
def test_scrypt_and_aes_gcm_aad():
    h = hash_password("MatKhau@12345")
    assert h.startswith("scrypt$32768$8$1$") and verify_password("MatKhau@12345", h)
    assert not verify_password("sai-mat-khau", h)
    c = FieldCipher(b"k" * 32)
    tok = c.encrypt("Bin", "children.nickname")
    assert c.decrypt(tok, "children.nickname") == "Bin"
    with pytest.raises(Exception):
        c.decrypt(tok, "devices.hostname")  # AAD sai => thẻ xác thực GCM không khớp


def test_canonical_json_same_on_server_and_agent():
    obj = {"z": [1, {"b": True, "a": "Tiếng Việt"}], "a": None}
    assert server_canon(obj) == agent_canon(obj)


# ------------------------------------------------------------------ đăng nhập & CSRF
def test_login_lockout_after_5_failures(client):
    make_parent(client, "a@x.vn")
    for _ in range(5):
        assert client.post("/auth/login", data={"email": "a@x.vn", "password": "sai-mat-khau-01"}).status_code == 401
    r = client.post("/auth/login", data={"email": "a@x.vn", "password": "MatKhau@12345"})
    assert r.status_code == 423 and "tạm khóa" in r.text  # đúng mật khẩu vẫn bị khóa 15 phút


def test_write_without_csrf_rejected(client):
    _, cid = make_parent(client, "a@x.vn")
    login(client, "a@x.vn")
    r = client.post(f"/children/{cid}/policy/time", data={"weekday_min": 999})
    assert r.status_code == 403


def test_logout_destroys_server_session(client):
    make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    raw = client.cookies.get("ogk_session")
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    client.cookies.set("ogk_session", raw)  # kẻ gian giữ lại cookie cũ
    assert client.get("/", follow_redirects=False).status_code == 303


# ------------------------------------------------------------------ IDOR
def test_idor_parent_b_cannot_touch_child_of_a(client):
    _, cid_a = make_parent(client, "a@x.vn")
    make_parent(client, "b@x.vn", kid="Na")
    csrf_a = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf_a, cid_a))
    client.post("/api/unlock-requests", json={"minutes": 15, "reason": "xin ạ"}, headers=bearer(dev["access_token"]))
    client.cookies.clear()
    csrf_b = login(client, "b@x.vn")
    assert client.get(f"/children/{cid_a}").status_code == 404
    assert client.get(f"/children/{cid_a}/export.csv").status_code == 404
    h = {"X-CSRF-Token": csrf_b, "HX-Request": "true"}
    assert client.post(f"/children/{cid_a}/policy/time", data={"weekday_min": 999}, headers=h).status_code == 404
    assert client.post(f"/devices/{dev['device_id']}/command", data={"cmd": "unlock"}, headers=h).status_code == 404
    assert client.post("/requests/1/approve", data={}, headers=h).status_code == 404
    assert client.post(f"/children/{cid_a}/purge", data={"confirm": "Bin"}, headers=h).status_code == 404


# ------------------------------------------------------------------ ghép đôi -> heartbeat -> chính sách
def test_enroll_heartbeat_policy_roundtrip(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    code = new_code(client, csrf, cid)
    dev = enroll(client, code)
    assert client.post("/api/enroll", json={"code": code, "fingerprint": "g" * 64}).status_code == 400  # dùng 1 lần
    verifier = PolicyVerifier(dev["device_id"], dev["policy_alg"], dev["policy_public_key"])
    body = verifier.verify(client.get("/api/policy", headers=bearer(dev["access_token"])).json(), 0)
    assert body["device_id"] == dev["device_id"] and body["profile"]["nickname"] == "Bin"
    assert len(body["categories"]) >= 200
    v1 = body["version"]
    # phụ huynh đổi quota trên dashboard
    r = client.post(f"/children/{cid}/policy/time", data={"weekday_min": 45, "weekend_min": 100, "budget_games": 30},
                    headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    assert r.status_code == 200 and "Đã lưu" in r.text
    hb = client.post("/api/heartbeat", json={"policy_version": v1, "client_time": time.time(),
                                             "state": {"day": "2026-11-19", "used_sec": 600}},
                     headers=bearer(dev["access_token"])).json()
    assert hb["policy_version"] == v1 + 1 and abs(hb["server_time"] - time.time()) < 5
    body2 = verifier.verify(client.get("/api/policy", headers=bearer(dev["access_token"])).json(), v1)
    assert body2["quota"]["weekday_min"] == 45 and body2["category_budgets"] == {"games": 30}
    # audit ghi giá trị cũ và mới
    page = client.get(f"/children/{cid}?tab=audit").text
    assert "từ 90 phút thành 45 phút" in page


def test_pairing_code_expired_and_rate_limited(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    code = new_code(client, csrf, cid)
    from server import db as dbmod
    from server.models import PairingCode
    with dbmod.SessionLocal() as db:
        for pc in db.query(PairingCode).all():
            pc.expires_at = time.time() - 1
        db.commit()
    assert client.post("/api/enroll", json={"code": code, "fingerprint": "f" * 64}).status_code == 400
    codes = [client.post("/api/enroll", json={"code": "AAAA-AAAA", "fingerprint": "f" * 64}).status_code for _ in range(6)]
    assert codes[-1] == 429  # quá 5 lần/phút/IP


# ------------------------------------------------------------------ sự kiện idempotent
def test_event_batch_sent_twice_is_not_duplicated(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    batch = [{"idem_key": str(uuid.uuid4()), "ts": time.time(), "type": "domain_query", "subject": "m.vnexpress.net"}
             for _ in range(5)]
    batch.append({"idem_key": str(uuid.uuid4()), "ts": time.time(), "type": "keylogger", "subject": "x"})  # type lạ
    r1 = client.post("/api/events", json={"events": batch}, headers=bearer(dev["access_token"])).json()
    r2 = client.post("/api/events", json={"events": batch}, headers=bearer(dev["access_token"])).json()
    assert r1["inserted"] == 5 and r1["rejected"][0]["error"] == "type"
    assert r2["inserted"] == 0 and r2["duplicates"] == 5
    assert len(r2["acked"]) == 6  # ACK cả sự kiện hỏng để agent bỏ khỏi hàng đợi
    from server import db as dbmod
    from server.models import Event
    with dbmod.SessionLocal() as db:
        subjects = {e.subject for e in db.query(Event).filter(Event.type == "domain_query")}
    assert subjects == {"vnexpress.net"}  # server ép tên miền cấp hai


def test_events_batch_limit(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    big = [{"idem_key": str(uuid.uuid4()), "ts": time.time(), "type": "app_start", "subject": "a.exe"} for _ in range(201)]
    assert client.post("/api/events", json={"events": big}, headers=bearer(dev["access_token"])).status_code == 422


# ------------------------------------------------------------------ token
def test_refresh_rotation_and_reuse_detection(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    r1 = client.post("/api/token/refresh", json={"refresh_token": dev["refresh_token"]}).json()
    assert r1["refresh_token"] != dev["refresh_token"]
    # kẻ trộm dùng lại refresh token CŨ => cả họ token bị thu hồi
    assert client.post("/api/token/refresh", json={"refresh_token": dev["refresh_token"]}).status_code == 401
    assert client.post("/api/token/refresh", json={"refresh_token": r1["refresh_token"]}).status_code == 401


def test_revoked_device_rejected_immediately(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    client.post(f"/devices/{dev['device_id']}/revoke", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    assert client.get("/api/policy", headers=bearer(dev["access_token"])).status_code == 401


# ------------------------------------------------------------------ lệnh khẩn: WebSocket + heartbeat, áp dụng 1 lần
def test_emergency_command_applied_once_via_ws_and_heartbeat(client, tmp_path):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    cache = LocalCache(tmp_path / "agent.db")
    core = AgentCore(TrustedClock())
    core.tick()

    def apply(cmd):
        if cache.mark_command_applied(cmd["command_id"]):
            core.apply_command(cmd["cmd"], cmd["payload"])

    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "auth", "access_token": dev["access_token"]})
        assert ws.receive_json()["type"] == "auth_ok"
        t0 = time.perf_counter()
        r = client.post(f"/devices/{dev['device_id']}/command", data={"cmd": "add_time", "minutes": "15"},
                        headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert "tức thì" in r.text
        msg = ws.receive_json()
        assert time.perf_counter() - t0 < 5  # yêu cầu đề: lệnh khẩn < 5 giây
        assert msg["type"] == "command" and msg["cmd"] == "add_time"
        apply(msg)
        # heartbeat cũng chở lệnh (dự phòng) trước khi kịp ack => agent phải bỏ qua lần 2
        hb = client.post("/api/heartbeat", json={"policy_version": 1}, headers=bearer(dev["access_token"])).json()
        assert hb["commands"][0]["command_id"] == msg["command_id"]
        apply(hb["commands"][0])
        ws.send_json({"type": "ack", "command_id": msg["command_id"]})
        time.sleep(0.2)
    assert core.bonus_min == 15  # chỉ cộng MỘT lần
    hb = client.post("/api/heartbeat", json={"policy_version": 1}, headers=bearer(dev["access_token"])).json()
    assert hb["commands"] == []  # đã ack thì không gửi lại


def test_ws_rejects_bad_token(client):
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "auth", "access_token": "x.y"})
        with pytest.raises(Exception):
            ws.receive_json()


# ------------------------------------------------------------------ yêu cầu thêm giờ & xóa dữ liệu
def test_unlock_request_approve_flow_and_purge(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    rid = client.post("/api/unlock-requests", json={"minutes": 30, "reason": "Con làm bài Scratch"},
                      headers=bearer(dev["access_token"])).json()["id"]
    assert "Con làm bài Scratch" in client.get("/partials/requests").text
    client.post(f"/requests/{rid}/approve", data={"minutes": "30", "note": "Nhớ nghỉ mắt nha"},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    hb = client.post("/api/heartbeat", json={"policy_version": 1}, headers=bearer(dev["access_token"])).json()
    assert hb["requests"][0]["status"] == "approved" and hb["requests"][0]["note"] == "Nhớ nghỉ mắt nha"
    assert hb["commands"][0]["cmd"] == "add_time" and hb["commands"][0]["payload"]["minutes"] == 30
    r = client.post(f"/children/{cid}/purge", data={"confirm": "Bin"}, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    assert "Đã xóa" in r.text
    hb = client.post("/api/heartbeat", json={"policy_version": 1}, headers=bearer(dev["access_token"])).json()
    assert any(c["cmd"] == "purge_data" for c in hb["commands"])


def test_retention_job_deletes_old_events(client):
    _, cid = make_parent(client, "a@x.vn")
    from server import db as dbmod
    from server.jobs import purge_expired
    from server.models import Event
    with dbmod.SessionLocal() as db:
        for age_days in (91, 10):
            db.add(Event(idem_key=str(uuid.uuid4()), ts=time.time() - age_days * 86400, device_id="d", child_id=cid,
                         type="app_start", subject="a.exe", duration_sec=0))
        db.commit()
        assert purge_expired(db)["events"] == 1
        assert db.query(Event).count() == 1


# ------------------------------------------------------------------ render trang
def test_pages_render(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    client.post("/api/heartbeat", json={"policy_version": 1, "state": {"day": "2026-11-19", "used_sec": 1200,
                                        "by_category": {"games": 600}, "phase": "active", "remaining_sec": 3000}},
                headers=bearer(dev["access_token"]))
    for url in ["/", "/family", "/children/new", "/partials/overview", "/partials/requests"] + \
               [f"/children/{cid}?tab={t}" for t in ("report", "time", "filter", "devices", "audit")]:
        r = client.get(url)
        assert r.status_code == 200, url
    assert "Lịch tuần" in client.get(f"/children/{cid}?tab=time").text
    r = client.post(f"/children/{cid}/kid-link", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    token = re.search(r"/kid/([\w-]+)", r.text).group(1)
    client.cookies.clear()
    kid = client.get(f"/kid/{token}")
    assert kid.status_code == 200 and "cũng thấy đúng những thông tin này" in kid.text
    assert client.get("/kid/khong-ton-tai").status_code == 404


# ------------------------------------------------------------------ giao diện mới: form gộp, trạng thái, link trẻ
def test_combined_policy_form_saves_everything_once(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    verifier = PolicyVerifier(dev["device_id"], dev["policy_alg"], dev["policy_public_key"])
    v1 = verifier.verify(client.get("/api/policy", headers=bearer(dev["access_token"])).json(), 0)["version"]
    form = {"weekday_min": "60", "weekend_min": "120", "budget_games": "30", "schedule": "1" * 336,
            "blocked_categories": ["social", "games", "khong-hop-le"], "safesearch": "on",
            "dns_block": "test-block.example\n<script>", "dns_allow": "khanacademy.org"}
    r = client.post(f"/children/{cid}/policy", data=form, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    assert r.status_code == 200 and "Đã lưu" in r.text and 'id="policy-ver" hx-swap-oob="true"' in r.text
    body = verifier.verify(client.get("/api/policy", headers=bearer(dev["access_token"])).json(), v1)
    assert body["version"] == v1 + 1  # MỘT lần lưu = MỘT phiên bản
    assert body["quota"] == {"weekday_min": 60, "weekend_min": 120} and body["category_budgets"] == {"games": 30}
    assert body["dns"]["blocked_categories"] == ["social", "games"]  # giá trị lạ bị loại
    assert body["dns"]["block"] == ["test-block.example"] and body["dns"]["safesearch"] and not body["dns"]["block_doh"]
    bad = client.post(f"/children/{cid}/policy", data={**form, "schedule": "1" * 10},
                      headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    assert bad.status_code == 400 and "Lịch không hợp lệ" in bad.text
    # phụ huynh khác không đụng được (IDOR => 404)
    make_parent(client, "b@x.vn")
    csrf_b = login(client, "b@x.vn")
    assert client.post(f"/children/{cid}/policy", data=form, headers={"X-CSRF-Token": csrf_b}).status_code == 404


def test_status_partial_shows_category_only_and_timed_break(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    dev = enroll(client, new_code(client, csrf, cid))
    client.post("/api/heartbeat", json={"policy_version": 1, "state": {
        "phase": "active", "remaining_sec": 1800, "quota_min": 90, "running": ["education", "chrome.exe"]}},
        headers=bearer(dev["access_token"]))
    st = client.get("/partials/status").text
    assert "Đang học tập" in st and "chrome.exe" not in st and 'hx-swap-oob="true"' in st
    r = client.post(f"/devices/{dev['device_id']}/command", data={"cmd": "lock_now", "minutes": "120"},
                    headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
    assert r.status_code == 200
    hb = client.post("/api/heartbeat", json={"policy_version": 1}, headers=bearer(dev["access_token"])).json()
    assert hb["commands"][0]["cmd"] == "lock_now" and hb["commands"][0]["payload"]["minutes"] == 120
    assert "tạm nghỉ 120 phút" in client.get(f"/children/{cid}").text  # nhật ký ghi rõ thời hạn


def test_new_kid_link_revokes_old_one_and_kid_page_has_no_block_count(client):
    _, cid = make_parent(client, "a@x.vn")
    csrf = login(client, "a@x.vn")
    h = {"X-CSRF-Token": csrf, "HX-Request": "true"}
    t1 = re.search(r"/kid/([\w-]+)", client.post(f"/children/{cid}/kid-link", headers=h).text).group(1)
    t2 = re.search(r"/kid/([\w-]+)", client.post(f"/children/{cid}/kid-link", headers=h).text).group(1)
    client.cookies.clear()
    assert client.get(f"/kid/{t1}").status_code == 404  # link cũ hết hiệu lực
    page = client.get(f"/kid/{t2}").text
    assert "Hôm nay của con" in page and "Huy hiệu" in page and "Bị chặn" not in page
