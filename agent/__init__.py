"""OGK-Agent: Windows Service (SYSTEM) + Tray UI cho trẻ (OGK Kids).

Phần lõi (dns_wire, domain_rules, clock, schedule, core, app_control,
policy_verify, local_cache) là logic thuần, test được trên mọi hệ điều hành.
Phần vỏ Windows (service, ipc pipe, netguard, winsys) chỉ import pywin32
bên trong hàm hoặc sau kiểm tra sys.platform == "win32".
"""

__version__ = "0.1.0"
