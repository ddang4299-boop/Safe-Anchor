"""Unit test: quyết định chặn theo hậu tố nhãn, allow thắng block, SafeSearch, DoH, tên miền cấp hai."""
from agent.domain_rules import DnsPolicyEngine, DomainSet, CategoryMap, registrable_domain


def make_engine(**kw):
    return DnsPolicyEngine(
        block=DomainSet(kw.get("block", ["facebook.com"])),
        allow=DomainSet(kw.get("allow", [])),
        categories=CategoryMap(kw.get("categories", {"roblox.com": "games", "tiktok.com": "social"})),
        blocked_categories=frozenset(kw.get("blocked_categories", ["social"])),
        exhausted_categories=frozenset(kw.get("exhausted", [])),
    )


def test_suffix_match_blocks_subdomains_not_lookalikes():
    e = make_engine()
    assert e.decide("facebook.com").action == "block"
    assert e.decide("m.facebook.com.").action == "block"  # FQDN có dấu chấm cuối
    assert e.decide("A.B.FACEBOOK.COM").action == "block"  # không phân biệt hoa thường
    assert e.decide("notfacebook.com").action == "forward"  # KHÔNG chặn nhầm
    assert e.decide("facebook.com.evil.example").action == "forward"


def test_allow_wins_over_block():
    e = make_engine(block=["example.com"], allow=["docs.example.com"])
    assert e.decide("docs.example.com").action == "forward"
    assert e.decide("www.example.com").action == "block"


def test_category_block_and_budget():
    e = make_engine(exhausted=["games"])
    d = e.decide("www.tiktok.com")
    assert d.action == "block" and d.reason == "category"
    d = e.decide("web.roblox.com")
    assert d.action == "block" and d.reason == "budget"


def test_safesearch_cname_targets():
    e = make_engine()
    assert e.decide("www.google.com").cname_target == "forcesafesearch.google.com"
    assert e.decide("www.google.com.vn").cname_target == "forcesafesearch.google.com"
    assert e.decide("www.youtube.com").cname_target == "restrict.youtube.com"
    assert e.decide("www.bing.com").cname_target == "strict.bing.com"
    assert e.decide("duckduckgo.com").cname_target == "safe.duckduckgo.com"
    # chính máy chủ đích không bị viết lại (tránh vòng lặp CNAME)
    assert e.decide("forcesafesearch.google.com").action == "forward"


def test_doh_endpoints_and_canary():
    e = make_engine()
    for name in ["dns.google", "cloudflare-dns.com", "mozilla.cloudflare-dns.com", "doh.opendns.com"]:
        d = e.decide(name)
        assert d.action == "block" and d.is_system
    assert e.decide("use-application-dns.net").reason == "canary"


def test_registrable_domain():
    assert registrable_domain("m.vnexpress.net") == "vnexpress.net"
    assert registrable_domain("thcs.hcm.edu.vn") == "hcm.edu.vn"
    assert registrable_domain("www.bbc.co.uk") == "bbc.co.uk"
    assert registrable_domain("example.com.") == "example.com"
