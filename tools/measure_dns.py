"""
tools/measure_dns.py — Đo độ trễ phân giải DNS p50/p95 CÓ và KHÔNG CÓ agent (M4, >= 30 mẫu).

    python tools/measure_dns.py --proxy 127.0.0.1:53 --direct 1.1.1.1:53 --samples 60

Phương pháp: gửi truy vấn A cho danh sách tên miền cố định, đo thời gian từ lúc gửi tới lúc nhận
(time.perf_counter, độ phân giải micro giây). Mỗi tên miền đo 2 lượt: lượt "lạnh" (cache trống) và
lượt "nóng" (trúng cache của proxy) — báo cáo riêng vì cache hấp thụ phần lớn truy vấn lặp.
Kết quả thật phụ thuộc mạng của bạn: KHÔNG chép số liệu mẫu vào báo cáo, hãy tự chạy.
"""
import argparse
import os
import socket
import statistics
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import dns_wire as w  # noqa: E402

DOMAINS = ["example.com", "example.org", "wikipedia.org", "khanacademy.org", "vnexpress.net", "tuoitre.vn",
           "python.org", "mozilla.org", "github.com", "olm.vn", "hocmai.vn", "duolingo.com", "bbc.com",
           "nasa.gov", "britannica.com", "code.org", "w3schools.com", "ted.com", "coursera.org", "edx.org"]


def query(server: tuple, name: str, timeout=3.0) -> float | None:
    qid = struct.unpack("!H", os.urandom(2))[0]
    pkt = w.build_query(name, w.TYPE_A, qid)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t0 = time.perf_counter()
        s.sendto(pkt, server)
        try:
            data, _ = s.recvfrom(4096)
        except socket.timeout:
            return None
        dt = (time.perf_counter() - t0) * 1000
    return dt if w.get_id(data) == qid else None


def pct(xs, p):
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1)))))
    return xs[k]


def run(label: str, server: tuple, samples: int) -> None:
    cold, warm = [], []
    names = (DOMAINS * ((samples // len(DOMAINS)) + 1))[:samples]
    seen = set()
    for n in names:
        dt = query(server, n)
        if dt is None:
            continue
        (warm if n in seen else cold).append(dt)
        seen.add(n)
        dt2 = query(server, n)
        if dt2 is not None:
            warm.append(dt2)
    for kind, xs in (("lạnh (lần đầu)", cold), ("nóng (lặp lại)", warm)):
        if xs:
            print(f"{label:8} {kind:15} n={len(xs):3}  p50={statistics.median(xs):7.2f} ms  p95={pct(xs, 95):7.2f} ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default="127.0.0.1:53")
    ap.add_argument("--direct", default="1.1.1.1:53")
    ap.add_argument("--samples", type=int, default=40)
    a = ap.parse_args()
    for label, spec in (("agent", a.proxy), ("trực tiếp", a.direct)):
        host, port = spec.rsplit(":", 1)
        run(label, (host, int(port)), a.samples)


if __name__ == "__main__":
    main()
