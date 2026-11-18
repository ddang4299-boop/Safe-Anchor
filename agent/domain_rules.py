"""
agent/domain_rules.py — Quyết định chặn / cho phép / ép SafeSearch cho một tên miền.

Yêu cầu đề: F2 (chặn theo tên miền VÀ mọi tên miền con, SafeSearch bằng CNAME,
đối phó DoH), F3 (subject là tên miền cấp hai).

Ý tưởng then chốt — SO KHỚP HẬU TỐ THEO NHÃN (label-wise suffix match):
    "a.b.facebook.com" sinh ra các hậu tố: a.b.facebook.com, b.facebook.com,
    facebook.com, com. Tên bị chặn nếu MỘT hậu tố nằm trong tập chặn.
    => "m.facebook.com" bị chặn (hậu tố facebook.com), còn "notfacebook.com"
       KHÔNG bị chặn vì hậu tố của nó là notfacebook.com, com — không có facebook.com.
    Nếu so khớp chuỗi thô kiểu name.endswith("facebook.com") sẽ chặn nhầm notfacebook.com.

Độ phức tạp: O(số nhãn) phép tra set (băm, O(1) trung bình) — tên miền có tối đa
127 nhãn nhưng thực tế 2–5, nên mỗi truy vấn chỉ tốn vài phép tra. Không cần trie.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Hậu tố "nhiều nhãn" phổ biến để tính tên miền cấp hai (eTLD+1) mà không cần
# tải Public Suffix List đầy đủ. Đủ cho bộ dữ liệu VN + quốc tế của đồ án.
MULTI_LABEL_SUFFIXES = {
    "com.vn", "net.vn", "org.vn", "edu.vn", "gov.vn", "ac.vn", "info.vn", "biz.vn", "name.vn",
    "health.vn", "int.vn", "pro.vn",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "edu.au",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "co.kr", "or.kr", "com.sg", "edu.sg", "com.cn",
    "com.tw", "com.hk", "co.th", "co.id", "com.my", "com.br", "co.nz", "co.in",
}

# Firefox: nếu tên miền canary này trả NXDOMAIN, Firefox tự TẮT DoH mặc định
# (https://support.mozilla.org/kb/canary-domain-use-application-dnsnet).
DOH_CANARY = "use-application-dns.net"

# Danh sách điểm cuối DoH công khai phổ biến. Trả NXDOMAIN => trình duyệt
# không phân giải được máy chủ DoH => quay về dùng DNS hệ thống (tức là proxy của ta).
DOH_ENDPOINTS = {
    "dns.google", "dns.google.com", "8888.google",
    "cloudflare-dns.com", "mozilla.cloudflare-dns.com", "chrome.cloudflare-dns.com",
    "one.one.one.one", "1dot1dot1dot1.cloudflare-dns.com", "security.cloudflare-dns.com",
    "family.cloudflare-dns.com",
    "dns.quad9.net", "dns9.quad9.net", "dns10.quad9.net", "dns11.quad9.net",
    "doh.opendns.com", "doh.familyshield.opendns.com",
    "dns.nextdns.io", "doh.cleanbrowsing.org", "dns.adguard.com", "dns.adguard-dns.com",
    "doh.dns.sb", "dns.alidns.com", "doh.pub", "dns.twnic.tw", "doh.mullvad.net",
    "dns.controld.com", "freedns.controld.com", "ordns.he.net", "odvr.nic.cz",
    "doh.libredns.gr", "dns.switch.ch", "doh.applied-privacy.net",
}

# SafeSearch: thay vì trả IP thật của google.com, ta trả CNAME tới máy chủ "bắt buộc
# SafeSearch" do chính nhà cung cấp vận hành. Trình duyệt vẫn kết nối HTTPS với
# chứng chỉ hợp lệ của *.google.com nên không có lỗi TLS.
_GOOGLE_TLDS = ["com", "com.vn", "co.uk", "co.jp", "com.au", "ca", "de", "fr", "co.in", "com.sg"]
SAFESEARCH_MAP: dict[str, str] = {}
for _tld in _GOOGLE_TLDS:
    SAFESEARCH_MAP[f"google.{_tld}"] = "forcesafesearch.google.com"
    SAFESEARCH_MAP[f"www.google.{_tld}"] = "forcesafesearch.google.com"
SAFESEARCH_MAP.update({
    "www.youtube.com": "restrict.youtube.com",
    "m.youtube.com": "restrict.youtube.com",
    "youtube.com": "restrict.youtube.com",
    "youtubei.googleapis.com": "restrict.youtube.com",
    "youtube.googleapis.com": "restrict.youtube.com",
    "www.youtube-nocookie.com": "restrict.youtube.com",
    "www.bing.com": "strict.bing.com",
    "bing.com": "strict.bing.com",
    "duckduckgo.com": "safe.duckduckgo.com",
    "www.duckduckgo.com": "safe.duckduckgo.com",
})

CATEGORIES = ("education", "entertainment", "social", "games", "inappropriate", "uncategorized")


def normalize(name: str) -> str:
    """Chuẩn hóa: chữ thường, bỏ dấu chấm cuối (FQDN), bỏ khoảng trắng."""
    return name.strip().rstrip(".").lower()


def suffixes(name: str) -> list[str]:
    """'a.b.c' -> ['a.b.c', 'b.c', 'c'] (từ cụ thể nhất tới chung nhất)."""
    labels = normalize(name).split(".")
    return [".".join(labels[i:]) for i in range(len(labels))]


def registrable_domain(name: str) -> str:
    """Tên miền cấp hai (eTLD+1): 'm.vnexpress.net' -> 'vnexpress.net',
    'thcs.hcm.edu.vn' -> 'hcm.edu.vn'. Đây là 'subject' được lưu (tối thiểu hóa dữ liệu P2)."""
    labels = normalize(name).split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in MULTI_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


class DomainSet:
    """Tập tên miền hỗ trợ so khớp hậu tố theo nhãn."""

    def __init__(self, domains=()):
        self._set = {normalize(d) for d in domains if d and normalize(d)}

    def match(self, name: str) -> str | None:
        for s in suffixes(name):
            if s in self._set:
                return s
        return None

    def __contains__(self, name: str) -> bool:
        return self.match(name) is not None

    def __len__(self) -> int:
        return len(self._set)


class CategoryMap:
    """Bảng phân loại tên miền -> nhóm, tra theo hậu tố cụ thể nhất."""

    def __init__(self, mapping: dict[str, str] | None = None):
        self._map = {normalize(k): v for k, v in (mapping or {}).items()}

    def category(self, name: str) -> str:
        for s in suffixes(name):
            cat = self._map.get(s)
            if cat:
                return cat
        return "uncategorized"

    def __len__(self) -> int:
        return len(self._map)


@dataclass
class DnsDecision:
    action: str  # "forward" | "block" | "safesearch"
    reason: str = ""  # "canary" | "doh" | "blocklist" | "category" | "budget" | "safesearch" | ""
    category: str = "uncategorized"
    matched: str | None = None
    cname_target: str | None = None

    @property
    def is_system(self) -> bool:
        """Chặn do hạ tầng (DoH/canary) — không tính là "trẻ cố vào trang bị chặn"."""
        return self.reason in ("canary", "doh")


@dataclass
class DnsPolicyEngine:
    """Bộ máy quyết định thuần (không I/O) => test được trên mọi hệ điều hành."""

    block: DomainSet = field(default_factory=DomainSet)
    allow: DomainSet = field(default_factory=DomainSet)
    categories: CategoryMap = field(default_factory=CategoryMap)
    blocked_categories: frozenset = frozenset()
    exhausted_categories: frozenset = frozenset()  # nhóm đã hết ngân sách giờ hôm nay (vd games)
    safesearch: bool = True
    block_doh: bool = True

    @classmethod
    def from_policy(cls, policy: dict, exhausted: frozenset = frozenset()) -> "DnsPolicyEngine":
        dns = policy.get("dns", {})
        return cls(
            block=DomainSet(dns.get("block", [])),
            allow=DomainSet(dns.get("allow", [])),
            categories=CategoryMap(policy.get("categories", {})),
            blocked_categories=frozenset(dns.get("blocked_categories", [])),
            exhausted_categories=exhausted,
            safesearch=bool(dns.get("safesearch", True)),
            block_doh=bool(dns.get("block_doh", True)),
        )

    def decide(self, qname: str) -> DnsDecision:
        name = normalize(qname)
        # 1) Canary DoH của Firefox: luôn NXDOMAIN để Firefox tự tắt DoH.
        if name == DOH_CANARY or name.endswith("." + DOH_CANARY):
            return DnsDecision("block", "canary", matched=DOH_CANARY)
        # 2) Điểm cuối DoH công khai.
        if self.block_doh:
            for s in suffixes(name):
                if s in DOH_ENDPOINTS:
                    return DnsDecision("block", "doh", matched=s)
        # 3) SafeSearch ưu tiên trước cả danh sách cho phép (cho phép google vẫn phải an toàn).
        if self.safesearch and name in SAFESEARCH_MAP:
            return DnsDecision("safesearch", "safesearch", cname_target=SAFESEARCH_MAP[name])
        category = self.categories.category(name)
        # 4) Danh sách CHO PHÉP thắng danh sách chặn (phụ huynh mở riêng một trang).
        m = self.allow.match(name)
        if m:
            return DnsDecision("forward", "allowlist", category, m)
        # 5) Danh sách chặn riêng của phụ huynh.
        m = self.block.match(name)
        if m:
            return DnsDecision("block", "blocklist", category, m)
        # 6) Chặn theo nhóm (vd social, inappropriate cho trẻ 6–11 tuổi).
        if category in self.blocked_categories:
            return DnsDecision("block", "category", category)
        # 7) Nhóm đã hết ngân sách thời gian hôm nay (vd trò chơi 45 phút).
        if category in self.exhausted_categories:
            return DnsDecision("block", "budget", category)
        return DnsDecision("forward", "", category)
