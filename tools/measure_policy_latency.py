"""
tools/measure_policy_latency.py — Đo độ trễ "phụ huynh bấm lệnh trên dashboard -> agent áp dụng" (M4).

Cách đo: đăng nhập dashboard bằng tài khoản demo, gửi N lệnh add_time 1 phút tới thiết bị, sau mỗi
lệnh hỏi agent qua IPC (get_status) cho tới khi quota_min tăng; thời gian = t_áp_dụng - t_gửi.
    python tools/measure_policy_latency.py --device <device_id> --samples 30
Yêu cầu: server và agent đang chạy trên cùng máy (hoặc chỉnh --server), agent đã ghép đôi.
"""
import argparse
import os
import re
import statistics
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.config import default_data_dir  # noqa: E402
from agent.ipc import IpcClient  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--email", default="demo@ogk.local")
    ap.add_argument("--password", default="OgkDemo@2026")
    ap.add_argument("--device", required=True)
    ap.add_argument("--samples", type=int, default=30)
    a = ap.parse_args()
    c = httpx.Client(base_url=a.server, follow_redirects=False)
    c.post("/auth/login", data={"email": a.email, "password": a.password})
    csrf = re.search(r'"X-CSRF-Token": "([^"]+)"', c.get("/").text).group(1)
    ipc = IpcClient(default_data_dir(False))
    out = []
    for i in range(a.samples):
        before = ipc.call("get_status")["status"]["quota_min"]
        t0 = time.perf_counter()
        c.post(f"/devices/{a.device}/command", data={"cmd": "add_time", "minutes": "5"},
               headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        while ipc.call("get_status")["status"]["quota_min"] == before:
            if time.perf_counter() - t0 > 90:
                break
            time.sleep(0.02)
        out.append((time.perf_counter() - t0) * 1000)
        print(f"mẫu {i + 1:2}: {out[-1]:.0f} ms")
    s = sorted(out)
    print(f"n={len(out)} p50={statistics.median(out):.0f} ms p95={s[int(0.95 * (len(s) - 1))]:.0f} ms max={max(out):.0f} ms")


if __name__ == "__main__":
    main()
