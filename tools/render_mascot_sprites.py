"""
tools/render_mascot_sprites.py — Render sẵn ảnh "atlas" mascot 3D cho Tray (PySide6 không có WebGL/Qt Quick 3D).

Ý tưởng "render trước, tương tác sau": dùng ĐÚNG mô hình three.js của trang web (dashboard/static/js/mascot3d.js)
để chụp mỗi nhân vật ở 24 góc xoay (15°/khung, nét mặt vui) + 5 nét mặt nhìn thẳng (cười tít, chớp mắt, buồn ngủ,
ngạc nhiên, thích thú). Tray ghép các khung này với co giãn / nhảy / hạt / bong bóng thoại vẽ bằng QPainter =>
trẻ kéo để xoay 360°, chạm để mascot phản ứng, mà máy không cần GPU hay trình duyệt nhúng.

Đầu ra: agent/tray/assets/3d/<nhân vật>.webp + <nhân vật>.json (kích thước ô, vị trí chân/đầu trong ô).
Chạy lại mỗi khi sửa mô hình 3D:
    .venv\\Scripts\\python.exe tools\\render_mascot_sprites.py [--cell 224] [--edge "C:\\...\\msedge.exe"]
Cần Microsoft Edge (có sẵn trên Windows 10/11). Không gửi gì ra Internet: chỉ một máy chủ tĩnh ở 127.0.0.1.
"""
from __future__ import annotations

import argparse
import base64
import functools
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dashboard" / "static"
OUT = ROOT / "agent" / "tray" / "assets" / "3d"
KINDS = ("tictac", "khien", "sao")
EXPRS = ("joy", "blink", "sleepy", "wow", "love")
YAWS = 24
COLS = 8

PAGE = """<!doctype html><meta charset="utf-8"><body style="margin:0;background:transparent">
<script type="module">
import * as THREE from "/js/vendor/three.module.min.js";
import { createScene } from "/js/mascot3d.js";
window.renderAtlas = (kind, cell, yaws, exprs, cols) => {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(cell, cell);
  const { scene, mascots } = createScene({ kinds: [kind], layout: "solo", reduced: true });
  const m = mascots[0];
  m.root.remove(m.shadow);                       // bóng đổ do Tray tự vẽ (co lại khi nhảy)
  const cam = new THREE.PerspectiveCamera(22, 1, 0.1, 50);
  cam.position.set(0, 1.4, 8.6);
  cam.lookAt(0, 1.3, 0);
  const total = yaws + exprs.length, rows = Math.ceil(total / cols);
  const out = document.createElement("canvas");
  out.width = cell * cols; out.height = cell * rows;
  const ctx = out.getContext("2d");
  const shoot = (i, yaw, expr) => {
    m.pose(yaw, expr);
    renderer.render(scene, cam);
    ctx.drawImage(renderer.domElement, (i % cols) * cell, Math.floor(i / cols) * cell);
  };
  for (let i = 0; i < yaws; i++) shoot(i, (i / yaws) * Math.PI * 2, "happy");
  exprs.forEach((e, k) => shoot(yaws + k, 0, e));
  const proj = (y) => { const v = new THREE.Vector3(0, y, 0).project(cam); return (-v.y * 0.5 + 0.5); };
  return { data: out.toDataURL("image/webp", 0.92), feet: proj(0), head: proj(m.headY), rows };
};
window.ready = true;
</script>"""


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript"}

    def do_GET(self):
        if self.path.split("?")[0] == "/__sprites.html":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *a):  # im lặng
        pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--cell", type=int, default=224, help="cạnh mỗi ô ảnh (px)")
    ap.add_argument("--edge", default=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", free_port()), functools.partial(Handler, directory=str(STATIC)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cdp = free_port()
    prof = Path(tempfile.mkdtemp(prefix="sa_sprites_"))
    edge = subprocess.Popen([args.edge, "--headless=new", "--no-first-run", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                             f"--user-data-dir={prof}", f"--remote-debugging-port={cdp}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(150):
            try:
                ws_url = next(t["webSocketDebuggerUrl"] for t in httpx.get(f"http://127.0.0.1:{cdp}/json").json() if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        if not ws_url:
            raise SystemExit("Không mở được Edge headless (kiểm tra --edge).")
        with connect(ws_url, max_size=None) as ws:
            n = 0

            def cmd(method, **params):
                nonlocal n
                n += 1
                ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    m = json.loads(ws.recv())
                    if m.get("id") == n:
                        if "error" in m:
                            raise RuntimeError(m["error"])
                        return m.get("result", {})

            def js(expr):
                r = cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                if "exceptionDetails" in r:
                    raise RuntimeError(r["exceptionDetails"])
                return r.get("result", {}).get("value")

            cmd("Page.navigate", url=f"http://127.0.0.1:{srv.server_address[1]}/__sprites.html")
            for _ in range(100):
                if js("window.ready === true"):
                    break
                time.sleep(0.1)
            else:
                raise SystemExit("Trang render không tải được module three.js / mascot3d.js.")
            OUT.mkdir(parents=True, exist_ok=True)
            for kind in KINDS:
                r = js(f"renderAtlas({json.dumps(kind)}, {args.cell}, {YAWS}, {json.dumps(list(EXPRS))}, {COLS})")
                img = base64.b64decode(r["data"].split(",", 1)[1])
                (OUT / f"{kind}.webp").write_bytes(img)
                meta = {"cell": args.cell, "cols": COLS, "rows": r["rows"], "yaw_frames": YAWS,
                        "exprs": {e: YAWS + i for i, e in enumerate(EXPRS)},
                        "feet": round(r["feet"], 4), "head": round(r["head"], 4),
                        "source": "dashboard/static/js/mascot3d.js (render bởi tools/render_mascot_sprites.py)"}
                (OUT / f"{kind}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"{kind}: {len(img) // 1024} KB, {YAWS + len(EXPRS)} khung, chân ở {meta['feet']:.2f} chiều cao ô")
    finally:
        edge.kill()
        srv.shutdown()
        time.sleep(0.5)
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    main()
