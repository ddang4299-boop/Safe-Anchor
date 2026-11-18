"""
agent/run_agent.py — Chạy agent ở chế độ CONSOLE (không cần cài dịch vụ) để phát triển và demo.

    python -m agent.run_agent enroll --code K7QM-2XPA --server http://127.0.0.1:8000
    python -m agent.run_agent run                       # DNS 127.0.0.1:53 (cần cổng 53 trống)
    python -m agent.run_agent run --dns-port 5353       # cổng khác để thử bằng nslookup -port=5353
    python -m agent.run_agent run --enforce             # THẬT SỰ kết thúc ứng dụng + khóa máy
    python -m agent.run_agent status                    # hỏi trạng thái qua IPC (như Tray)
    python -m agent.run_agent netguard-plan             # in các lệnh firewall/registry sẽ áp dụng

Mặc định enforce=False: chỉ ghi log "sẽ khóa/sẽ kết thúc" để không làm phiền máy phát triển.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

from .config import AgentConfig, default_data_dir


def _cfg(args) -> AgentConfig:
    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir(False)
    cfg = AgentConfig.load(data_dir)
    if getattr(args, "server", None):
        cfg.server_url = args.server
    return cfg


def cmd_enroll(args) -> int:
    from .local_cache import LocalCache
    from .sync import ServerClient
    cfg = _cfg(args)
    cfg.save()
    cache = LocalCache(Path(cfg.data_dir) / "agent.db")

    async def go():
        client = ServerClient(cfg, cache)
        try:
            data = await client.enroll(args.code)
            r = await client.call("GET", "/api/policy")
            cache.set("policy_envelope", r.json())
            return data
        finally:
            await client.close()

    try:
        data = asyncio.run(go())
    except Exception as exc:
        print(f"Ghép đôi thất bại: {exc}")
        return 1
    print(f"✓ Đã ghép đôi. device_id={data['device_id']} child_id={data['child_id']} thuật toán ký={data['policy_alg']}")
    return 0


def cmd_run(args) -> int:
    from .runtime import AgentRuntime
    cfg = _cfg(args)
    if args.dns_port is not None:
        cfg.dns_port = args.dns_port
    if args.no_dns:
        cfg.dns_enabled = False
    if args.enforce:
        cfg.enforce = True
    if args.upstream:
        cfg.upstreams = args.upstream
    rt = AgentRuntime(cfg, service_mode=False)

    async def main():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows: Ctrl+C sinh KeyboardInterrupt
                pass
        await rt.run(stop)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Đã dừng agent.")
    return 0


def cmd_status(args) -> int:
    from .ipc import IpcClient
    cfg = _cfg(args)
    try:
        r = IpcClient(Path(cfg.data_dir), cfg.ipc_tcp_port).call("get_status")
    except Exception as exc:
        print(f"Không kết nối được agent: {exc}")
        return 1
    st = r.get("status", {})
    st.pop("segments", None)
    print(json.dumps(st, ensure_ascii=False, indent=2))
    return 0


def cmd_netguard_plan(args) -> int:
    from . import netguard
    cfg = _cfg(args)
    for line in netguard.apply_all(cfg.upstreams, dry_run=True):
        print(line)
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="ogk-agent")
    ap.add_argument("--data-dir", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll")
    e.add_argument("--code", required=True)
    e.add_argument("--server", default=None)
    r = sub.add_parser("run")
    r.add_argument("--server", default=None)
    r.add_argument("--dns-port", type=int, default=None)
    r.add_argument("--no-dns", action="store_true")
    r.add_argument("--enforce", action="store_true")
    r.add_argument("--upstream", action="append", help="DNS upstream (lặp lại được)")
    sub.add_parser("status")
    sub.add_parser("netguard-plan")
    args = ap.parse_args(argv)
    return {"enroll": cmd_enroll, "run": cmd_run, "status": cmd_status, "netguard-plan": cmd_netguard_plan}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
