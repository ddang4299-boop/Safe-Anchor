"""
agent/netguard.py — Chống vượt rào ở tầng mạng: ép DNS card mạng, luật firewall, chính sách trình duyệt.

Yêu cầu đề: F2 (NÊN CÓ: chống DoH — chặn endpoint, canary, chính sách trình duyệt, chặn cổng 853;
chống đổi DNS thủ công — đặt lại DNS card mạng hoặc chặn cổng 53 đi ra).

Các hàm build_* là THUẦN (trả danh sách lệnh) => test được và in ra cho người đọc kiểm tra.
Hàm apply_* chỉ chạy khi cấu hình manage_network=True trên Windows với quyền SYSTEM/Admin.

Vì sao không "chặn cổng 53 cho mọi chương trình TRỪ dịch vụ OGK"? Windows Defender Firewall có
quy tắc: LUẬT CHẶN LUÔN THẮNG LUẬT CHO PHÉP (trừ luật IPsec "override block rules"). Không thể
viết "block 53 except ogk-agent". Ta dùng cách khác: chặn cổng 53 tới MỌI địa chỉ NGOẠI TRỪ các
upstream của agent (tính phần bù của dải IPv4). Hạn chế: trẻ hỏi thẳng chính upstream đó vẫn
qua => chọn upstream là resolver lọc cho gia đình. Giải pháp triệt để là bộ lọc WFP theo App-ID
(ghi trong docs/DECISIONS.md).
"""
from __future__ import annotations

import ipaddress
import json
import logging
import subprocess
import sys

log = logging.getLogger("ogk.netguard")

RULE_PREFIX = "OGK-"
# Resolver công khai thường bị dùng làm DoH bằng IP literal (https://1.1.1.1/dns-query): chặn TCP/UDP 443 tới chúng.
DOH_IPS = ["1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4", "9.9.9.9", "149.112.112.112",
           "208.67.222.222", "208.67.220.220", "94.140.14.14", "94.140.15.15", "45.90.28.0", "45.90.30.0"]

BROWSER_POLICIES = [
    # (khóa HKLM, tên giá trị, kiểu, dữ liệu)
    (r"SOFTWARE\Policies\Google\Chrome", "DnsOverHttpsMode", "REG_SZ", "off"),
    (r"SOFTWARE\Policies\Microsoft\Edge", "DnsOverHttpsMode", "REG_SZ", "off"),
    (r"SOFTWARE\Policies\Mozilla\Firefox\DNSOverHTTPS", "Enabled", "REG_DWORD", "0"),
    (r"SOFTWARE\Policies\Mozilla\Firefox\DNSOverHTTPS", "Locked", "REG_DWORD", "1"),
    (r"SOFTWARE\Policies\BraveSoftware\Brave", "DnsOverHttpsMode", "REG_SZ", "off"),
]


def complement_ranges(excluded: list[str]) -> list[str]:
    """Phần bù của tập IPv4 loại trừ, dạng 'a.b.c.d-e.f.g.h' cho netsh remoteip=.
    vd excluded=['8.8.8.8'] -> ['0.0.0.1-8.8.8.7', '8.8.8.9-255.255.255.254'] (bỏ 0.0.0.0 và broadcast)."""
    ips = sorted({int(ipaddress.IPv4Address(x)) for x in excluded})
    lo, hi = 1, 2 ** 32 - 2
    out, cur = [], lo
    for ip in ips:
        if ip > cur:
            out.append((cur, ip - 1))
        cur = max(cur, ip + 1)
    if cur <= hi:
        out.append((cur, hi))
    return [f"{ipaddress.IPv4Address(a)}-{ipaddress.IPv4Address(b)}" for a, b in out]


def build_firewall_commands(upstreams: list[str]) -> list[list[str]]:
    v4 = [u for u in upstreams if ":" not in u]
    # 127.0.0.1 luôn được loại trừ (Windows Firewall vốn không lọc loopback, ghi rõ cho chắc chắn)
    allowed_53 = ",".join(complement_ranges(v4 + ["127.0.0.1"]))
    doh = ",".join(ip for ip in DOH_IPS if ip not in v4) or "1.1.1.1"
    base = ["netsh", "advfirewall", "firewall", "add", "rule", "dir=out", "action=block", "enable=yes"]
    return [
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_PREFIX}DoT-853"],
        base + [f"name={RULE_PREFIX}DoT-853", "protocol=TCP", "remoteport=853"],
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_PREFIX}DNS-53-UDP"],
        base + [f"name={RULE_PREFIX}DNS-53-UDP", "protocol=UDP", "remoteport=53", f"remoteip={allowed_53}"],
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_PREFIX}DNS-53-TCP"],
        base + [f"name={RULE_PREFIX}DNS-53-TCP", "protocol=TCP", "remoteport=53", f"remoteip={allowed_53}"],
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_PREFIX}DoH-IP-443"],
        base + [f"name={RULE_PREFIX}DoH-IP-443", "protocol=TCP", "remoteport=443", f"remoteip={doh}"],
    ]


def build_browser_policy_commands() -> list[list[str]]:
    return [["reg", "add", f"HKLM\\{k}", "/v", name, "/t", typ, "/d", data, "/f"] for k, name, typ, data in BROWSER_POLICIES]


def _ps(script: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=30)
    return r.stdout


def get_adapter_dns() -> list[dict]:
    """[{InterfaceIndex, InterfaceAlias, ServerAddresses}] cho các card IPv4 đang có DNS."""
    if sys.platform != "win32":
        return []
    out = _ps("Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object {$_.ServerAddresses} | "
              "Select-Object InterfaceIndex,InterfaceAlias,ServerAddresses | ConvertTo-Json -Compress")
    data = json.loads(out or "[]")
    return data if isinstance(data, list) else [data]


def ensure_dns_loopback() -> list[str]:
    """Kiểm tra định kỳ: card nào bị đổi DNS (vd trẻ đặt 8.8.8.8) thì đặt lại 127.0.0.1.
    Trả danh sách card vừa sửa (để ghi cảnh báo toàn vẹn)."""
    fixed = []
    for a in get_adapter_dns():
        servers = a.get("ServerAddresses") or []
        if servers != ["127.0.0.1"]:
            _ps(f"Set-DnsClientServerAddress -InterfaceIndex {int(a['InterfaceIndex'])} -ServerAddresses 127.0.0.1")
            fixed.append(f"{a.get('InterfaceAlias')}: {servers}")
    return fixed


def apply_all(upstreams: list[str], dry_run: bool = True) -> list[str]:
    cmds = build_firewall_commands(upstreams) + build_browser_policy_commands()
    lines = [" ".join(c) for c in cmds]
    if dry_run or sys.platform != "win32":
        return lines
    for c in cmds:
        subprocess.run(c, capture_output=True)
    return lines
