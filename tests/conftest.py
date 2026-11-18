import os
import time

import pytest


@pytest.fixture
def server_env(tmp_path, monkeypatch):
    """Server độc lập cho mỗi test: DB + khóa riêng trong thư mục tạm."""
    monkeypatch.setenv("OGK_INSTANCE_DIR", str(tmp_path / "instance"))
    monkeypatch.setenv("OGK_DB_URL", f"sqlite:///{(tmp_path / 'ogk.db').as_posix()}")
    monkeypatch.setenv("OGK_COOKIE_SECURE", "0")
    for k in ("OGK_SECRET", "OGK_DATA_KEY", "OGK_SIGNING_KEY", "OGK_POLICY_ALG"):
        monkeypatch.delenv(k, raising=False)
    from server.config import Settings
    from server.main import create_app
    settings = Settings()
    app = create_app(settings, start_jobs=False)
    return app, settings


@pytest.fixture
def client(server_env):
    from fastapi.testclient import TestClient
    app, settings = server_env
    with TestClient(app) as c:
        c.settings = settings
        c.app_ctx = app.state.ctx
        yield c


def make_parent(client, email, password="MatKhau@12345", kid="Bin", birth_year=2018):
    """Tạo phụ huynh + 1 trẻ trực tiếp trong DB, trả (parent_id, child_id)."""
    from server import db as dbmod
    from server.models import Child, Guardian, Parent
    from server.policy_service import create_policy_version, default_policy_body
    from server.security import hash_password
    from agent import schedule as sch
    ctx = client.app_ctx
    with dbmod.SessionLocal() as db:
        p = Parent(email=email, pw_hash=hash_password(password), created_at=time.time())
        db.add(p)
        db.flush()
        db.add(Guardian(parent_id=p.id, relation="mẹ", display_name_enc=ctx.cipher.encrypt("Mẹ", "guardians.display_name"),
                        call_name_enc=ctx.cipher.encrypt("Mẹ", "guardians.call_name")))
        c = Child(parent_id=p.id, nickname_enc=ctx.cipher.encrypt(kid, "children.nickname"), self_pronoun="con",
                  birth_year=birth_year, avatar_key="tictac", created_at=time.time())
        db.add(c)
        db.flush()
        body = default_policy_body(birth_year)
        body["schedule"] = sch.daily_window("00:00", "23:30")
        create_policy_version(db, c.id, body)
        db.commit()
        return p.id, c.id


def login(client, email, password="MatKhau@12345"):
    from server.security import csrf_token, sha256_hex
    r = client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)
    assert r.status_code == 303, r.text
    raw = client.cookies.get("ogk_session")
    return csrf_token(client.settings.secret, sha256_hex(raw))
