"""Unit test: SHA-256 nhận diện tệp đổi tên, kiểm chữ ký chính sách, hàng đợi cục bộ idempotent."""
import base64
import hashlib
import os
import shutil

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from agent.app_control import AppController, AppRules, ProcInfo, is_protected
from agent.local_cache import LocalCache
from agent.policy_verify import PolicyRejected, PolicyVerifier, canonical_json, hmac_sign


# ---------------- app control ----------------
def test_renamed_exe_is_still_detected(tmp_path):
    original = tmp_path / "notepad.exe"
    original.write_bytes(b"MZ fake notepad binary " * 1000)
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    renamed = tmp_path / "game.exe"
    shutil.copy(original, renamed)
    ctl = AppController(AppRules(block_sha256={sha}))
    res = ctl.scan([ProcInfo(100, "game.exe", str(renamed))])
    assert len(res.to_kill) == 1 and res.to_kill[0][1] == "sha256"


def test_rename_to_system_name_outside_windows_is_not_protected(tmp_path):
    fake = tmp_path / "svchost.exe"
    fake.write_bytes(b"MZ game")
    sha = hashlib.sha256(fake.read_bytes()).hexdigest()
    assert not is_protected(ProcInfo(5, "svchost.exe", str(fake)))
    ctl = AppController(AppRules(block_sha256={sha}))
    assert ctl.scan([ProcInfo(5, "svchost.exe", str(fake))]).to_kill


def test_hash_cache_and_start_stop_events(tmp_path):
    exe = tmp_path / "paint.exe"
    exe.write_bytes(b"MZ paint")
    now = [0.0]
    ctl = AppController(AppRules(categories={"paint.exe": "education"}), mono=lambda: now[0])
    r1 = ctl.scan([ProcInfo(1, "paint.exe", str(exe))])
    assert [p.name for p in r1.started] == ["paint.exe"] and r1.running_categories == {"education"}
    now[0] = 42
    r2 = ctl.scan([])
    assert r2.stopped == [("paint.exe", 42)]


def test_budget_exhausted_kills_category(tmp_path):
    exe = tmp_path / "minecraft.exe"
    exe.write_bytes(b"MZ mc")
    ctl = AppController(AppRules(categories={"minecraft.exe": "games"}))
    res = ctl.scan([ProcInfo(9, "minecraft.exe", str(exe))], exhausted_categories=frozenset({"games"}))
    assert res.to_kill[0][1] == "budget"


# ---------------- policy verify ----------------
@pytest.fixture
def keys():
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return sk, base64.b64encode(pub).decode()


def sign(sk, body):
    return {"alg": "ed25519", "body": body, "sig": base64.b64encode(sk.sign(canonical_json(body))).decode()}


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": "Bé"}) == canonical_json({"a": "Bé", "b": 1}) == '{"a":"Bé","b":1}'.encode()


def test_valid_policy_accepted(keys):
    sk, pub = keys
    v = PolicyVerifier("dev-1", "ed25519", pub)
    body = v.verify(sign(sk, {"device_id": "dev-1", "version": 3, "quota": {"weekday_min": 90}}), current_version=2)
    assert body["version"] == 3


def test_tampered_policy_rejected(keys):
    sk, pub = keys
    env = sign(sk, {"device_id": "dev-1", "version": 3, "quota": {"weekday_min": 90}})
    env["body"]["quota"]["weekday_min"] = 999  # trẻ sửa quota trong cache
    with pytest.raises(PolicyRejected):
        PolicyVerifier("dev-1", "ed25519", pub).verify(env, 2)


def test_wrong_device_rejected(keys):
    sk, pub = keys
    with pytest.raises(PolicyRejected, match="thiết bị khác"):
        PolicyVerifier("dev-2", "ed25519", pub).verify(sign(sk, {"device_id": "dev-1", "version": 3}), 0)


def test_replay_old_version_rejected(keys):
    sk, pub = keys
    with pytest.raises(PolicyRejected, match="phát lại"):
        PolicyVerifier("dev-1", "ed25519", pub).verify(sign(sk, {"device_id": "dev-1", "version": 2}), 5)


def test_alg_downgrade_rejected(keys):
    _, pub = keys
    body = {"device_id": "dev-1", "version": 9}
    env = {"alg": "hmac-sha256", "body": body, "sig": hmac_sign(b"guess", body)}
    with pytest.raises(PolicyRejected, match="thuật toán"):
        PolicyVerifier("dev-1", "ed25519", pub).verify(env, 0)


def test_hmac_mode():
    key = os.urandom(32)
    body = {"device_id": "d", "version": 1}
    v = PolicyVerifier("d", "hmac-sha256", hmac_key=key)
    assert v.verify({"alg": "hmac-sha256", "body": body, "sig": hmac_sign(key, body)}, 0)["version"] == 1
    with pytest.raises(PolicyRejected):
        v.verify({"alg": "hmac-sha256", "body": {**body, "version": 2}, "sig": hmac_sign(key, body)}, 0)


# ---------------- local cache ----------------
def test_event_queue_idempotent_and_ack(tmp_path):
    c = LocalCache(tmp_path / "agent.db")
    k = c.enqueue_event({"type": "app_start", "subject": "paint.exe"})
    c.enqueue_event({"idem_key": k, "type": "app_start", "subject": "paint.exe"})  # trùng key
    assert c.queue_size() == 1
    batch = c.peek_events(200)
    assert batch[0]["idem_key"] == k
    c.ack_events([k])
    assert c.queue_size() == 0


def test_command_applied_once(tmp_path):
    c = LocalCache(tmp_path / "agent.db")
    assert c.mark_command_applied("cmd-1") is True  # đến qua WebSocket
    assert c.mark_command_applied("cmd-1") is False  # đến lần nữa qua heartbeat -> bỏ qua
