"""
server/main.py — Điểm vào OGK-Server.

Chạy thử (HTTP trong máy):  python -m server.main            -> http://127.0.0.1:8000
Chạy TLS (lab):              python -m server.main --tls     -> https://0.0.0.0:8443
                             (chạy python tools/gen_lab_ca.py trước để tạo CA + chứng chỉ)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db as dbmod
from .config import DASHBOARD_DIR, ROOT, get_settings
from .context import AppContext
from .jobs import retention_loop
from .models import Base
from .policy_service import load_categories_csv
from .routers import agent_api, auth, dashboard, kid
from .web import LoginRequired, render

# Windows đọc kiểu MIME từ registry: có máy map .js -> text/plain, khi đó trình duyệt (nosniff) từ chối chạy
# <script type="module"> (mascot 3D trang của trẻ). Cố định kiểu chuẩn thay vì phụ thuộc máy chạy server.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

log = logging.getLogger("ogk")


def create_app(settings=None, start_jobs: bool = True) -> FastAPI:
    settings = settings or get_settings()
    settings.instance_dir.mkdir(parents=True, exist_ok=True)
    engine = dbmod.init_engine(settings.db_url)
    Base.metadata.create_all(engine)
    with dbmod.SessionLocal() as db:
        load_categories_csv(db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(retention_loop(settings.retention_days)) if start_jobs else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="SafeAnchor Server", version="0.1.0", lifespan=lifespan,
                  description="API cho OGK-Agent (/api/*) và web dashboard phụ huynh.")
    app.state.ctx = AppContext(settings)
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR / "static")), name="static")
    app.include_router(auth.router)
    app.include_router(agent_api.router)
    app.include_router(dashboard.router)
    app.include_router(kid.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        if request.headers.get("hx-request"):
            return HTMLResponse("", status_code=401, headers={"HX-Redirect": "/auth/login"})
        return RedirectResponse("/auth/login", status_code=303)

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/") or request.headers.get("hx-request"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
        return render(request, "error.html", {"status": exc.status_code, "detail": exc.detail}, exc.status_code)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        return resp

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


def main():
    import uvicorn
    ap = argparse.ArgumentParser(description="OGK Server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--tls", action="store_true", help="bật HTTPS bằng chứng chỉ lab trong certs/")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    kwargs = {}
    if args.tls:
        certs = ROOT / "certs"
        kwargs = {"ssl_certfile": str(certs / "server.crt"), "ssl_keyfile": str(certs / "server.key")}
    port = args.port or (8443 if args.tls else 8000)
    uvicorn.run(create_app(), host=args.host, port=port, ws_ping_interval=20, ws_ping_timeout=20, **kwargs)


if __name__ == "__main__":
    main()
