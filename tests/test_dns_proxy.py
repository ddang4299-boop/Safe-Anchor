"""Tích hợp: DNS proxy thật trên cổng ngẫu nhiên + upstream giả (UDP và TCP)."""
import asyncio
import struct

import pytest

from agent import dns_wire as w
from agent.dns_proxy import DnsCache, DnsProxy, Upstream, tcp_exchange, udp_exchange
from agent.domain_rules import CategoryMap, DnsPolicyEngine, DomainSet


class FakeUpstream(asyncio.DatagramProtocol):
    """Upstream giả: trả A 192.0.2.10 cho mọi tên; 'big.example' trả TC=1 qua UDP."""

    def __init__(self):
        self.count = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.count += 1
        q = w.parse_message(data)
        if q.questions[0].name == "big.example":
            self.transport.sendto(w.build_truncated(q), addr)
            return
        self.transport.sendto(answer_for(q), addr)


def answer_for(q):
    if q.questions[0].qtype == w.TYPE_AAAA:
        return w.build_answer_response(q, [(None, w.TYPE_AAAA, 120, w.a_rdata("2001:db8::10"))])
    return w.build_answer_response(q, [(None, w.TYPE_A, 120, w.a_rdata("192.0.2.10"))])


async def start_fake_upstream():
    loop = asyncio.get_running_loop()
    proto = FakeUpstream()
    transport, _ = await loop.create_datagram_endpoint(lambda: proto, local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]

    async def tcp_handler(reader, writer):
        (n,) = struct.unpack("!H", await reader.readexactly(2))
        q = w.parse_message(await reader.readexactly(n))
        resp = answer_for(q)
        writer.write(struct.pack("!H", len(resp)) + resp)
        await writer.drain()
        writer.close()

    tcp = await asyncio.start_server(tcp_handler, "127.0.0.1", port)
    return proto, transport, tcp, port


@pytest.fixture
async def env():
    proto, utransport, utcp, uport = await start_fake_upstream()
    engine = DnsPolicyEngine(block=DomainSet(["blocked.example"]),
                             categories=CategoryMap({"tiktok.com": "social"}),
                             blocked_categories=frozenset({"social"}))
    events = []
    proxy = DnsProxy(lambda: engine, Upstream([("127.0.0.1", uport)], timeout=1.0),
                     host="127.0.0.1", port=0, on_event=lambda k, q, d: events.append((k, q.name, d.reason)))
    await proxy.start()
    yield proxy, proto, events
    await proxy.stop()
    utransport.close()
    utcp.close()


async def ask_udp(proxy, name, qtype=w.TYPE_A, qid=0x4242):
    raw = await udp_exchange(("127.0.0.1", proxy.port), w.build_query(name, qtype, qid), 2.0)
    return w.parse_message(raw)


async def test_forward_and_cache(env):
    proxy, upstream, _ = env
    r1 = await ask_udp(proxy, "www.example.com", qid=1)
    r2 = await ask_udp(proxy, "www.example.com", qid=2)
    assert r1.answers[0].value == "192.0.2.10"
    assert r2.header.id == 2  # cache vá ID đúng
    assert upstream.count == 1  # lần 2 trúng cache, không hỏi upstream
    assert r2.answers[0].ttl <= 120


async def test_block_subdomain_nxdomain_keeps_id(env):
    proxy, upstream, events = env
    r = await ask_udp(proxy, "a.b.blocked.example", qid=0x7777)
    assert r.header.rcode == w.RCODE_NXDOMAIN and r.header.id == 0x7777
    r = await ask_udp(proxy, "www.tiktok.com")
    assert r.header.rcode == w.RCODE_NXDOMAIN
    assert ("blocked", "www.tiktok.com", "category") in events
    assert upstream.count == 0  # miền bị chặn không bao giờ rời máy


async def test_tcp_query(env):
    proxy, _, _ = env
    raw = await tcp_exchange(("127.0.0.1", proxy.port), w.build_query("tcp.example", qid=9), 2.0)
    m = w.parse_message(raw)
    assert m.header.id == 9 and m.answers[0].value == "192.0.2.10"


async def test_truncated_upstream_falls_back_to_tcp(env):
    proxy, _, _ = env
    r = await ask_udp(proxy, "big.example")
    assert r.header.tc == 0 and r.answers and r.answers[0].value == "192.0.2.10"


async def test_safesearch_returns_cname_plus_a(env):
    proxy, _, _ = env
    r = await ask_udp(proxy, "www.google.com")
    assert r.answers[0].rtype == w.TYPE_CNAME
    assert r.answers[0].value == "forcesafesearch.google.com"
    assert r.answers[1].rtype == w.TYPE_A and r.answers[1].name == "forcesafesearch.google.com"


async def test_servfail_when_upstream_dead():
    engine = DnsPolicyEngine()
    proxy = DnsProxy(lambda: engine, Upstream([("127.0.0.1", 9)], timeout=0.3), port=0)
    await proxy.start()
    try:
        r = await ask_udp(proxy, "nowhere.example", qid=0x55)
        assert r.header.rcode == w.RCODE_SERVFAIL and r.header.id == 0x55
    finally:
        await proxy.stop()


async def test_concurrent_queries(env):
    proxy, _, _ = env
    results = await asyncio.gather(*[ask_udp(proxy, f"host{i}.example", qid=i) for i in range(50)])
    assert all(r.header.id == i and r.answers for i, r in enumerate(results))


async def test_malformed_gets_formerr(env):
    proxy, _, _ = env
    resp = await proxy.handle(b"\x12\x34\x01\x00\x00\x01", "udp")
    assert w.get_id(resp) == 0x1234 and resp[3] & 0xF == w.RCODE_FORMERR


def test_cache_ttl_expiry():
    now = [0.0]
    c = DnsCache(clock=lambda: now[0])
    q = w.parse_message(w.build_query("ttl.example", qid=1))
    c.put(q.questions[0], w.build_answer_response(q, [(None, w.TYPE_A, 10, w.a_rdata("192.0.2.1"))]))
    now[0] = 4
    assert w.parse_message(c.get(q.questions[0], 5)).answers[0].ttl == 6
    now[0] = 11
    assert c.get(q.questions[0], 5) is None
