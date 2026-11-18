"""
tools/measure_resources.py — Đo CPU/RAM của tiến trình agent (M4: lúc rảnh và lúc cao điểm, >= 30 mẫu).

    python tools/measure_resources.py --pid <PID agent> --samples 60 --interval 1
Lúc "cao điểm": trong khi đo, chạy song song  python tools/measure_dns.py --samples 400  để tạo tải DNS.
"""
import argparse
import statistics

import psutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--samples", type=int, default=60)
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()
    p = psutil.Process(a.pid)
    p.cpu_percent(None)
    cpu, rss = [], []
    for _ in range(a.samples):
        cpu.append(p.cpu_percent(a.interval) / psutil.cpu_count())  # % trên TOÀN máy
        rss.append(p.memory_info().rss / 2 ** 20)
    print(f"n={len(cpu)} CPU% p50={statistics.median(cpu):.2f} max={max(cpu):.2f} | "
          f"RAM MB p50={statistics.median(rss):.1f} max={max(rss):.1f}")


if __name__ == "__main__":
    main()
