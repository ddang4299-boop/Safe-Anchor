"""
agent/dns_proxy.py — DNS proxy cục bộ 127.0.0.1:53 (UDP + TCP) có lọc, SafeSearch, chống DoH.

Yêu cầu đề: F2 (BẮT BUỘC: proxy 127.0.0.1:53, chặn tên miền + tên miền con, NXDOMAIN giữ
ID, SERVFAIL khi upstream lỗi, xử lý đồng thời bằng asyncio, SafeSearch CNAME),
M1 (luồng gói tin), M4 (độ trễ p50/p95).

Luồng xử lý một truy vấn (xem docs/BACKEND_AND_NETWORK_GUIDE.md §1):

  trình duyệt -> stub resolver Windows (Dnscache) -> UDP 127.0.0.1:53 -> [DnsProxy.handle]
     1. parse_message()             : đọc gói, lỗi định dạng -> FORMERR
     2. engine.decide(qname)        : canary/DoH/SafeSearch/allow/block/category/budget
     3a. block      -> NXDOMAIN (giữ ID)            + sự kiện blocked_domain + toast cho Tray
     3b. safesearch -> CNAME forcesafesearch + A/AAAA tra động từ upstream
     3c. forward    -> tra cache TTL -> trúng: vá ID + TTL, trả ngay (~0.1 ms)
                                     -> trượt: hỏi upstream (UDP, TC=1 thì TCP) -> lưu cache
     4. upstream hết hạn/lỗi -> SERVFAIL (client sẽ thử lại / báo lỗi, không treo)

Đồng thời: mỗi gói UDP sinh một asyncio Task riêng => một truy vấn upstream chậm
(2 giây timeout) KHÔNG chặn các truy vấn khác. Semaphore giới hạn số truy vấn upstream
song song để tránh bị lạm dụng làm bộ khuếch đại.

Mỗi truy vấn upstream mở socket UDP với CỔNG NGUỒN NGẪU NHIÊN do hệ điều hành cấp và
kiểm tra ID + question của phản hồi => chống giả mạo phản hồi kiểu Kaminsky (cache poisoning).
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

from . import dns_wire as w
from .domain_rules import DnsDecision, DnsPolicyEngine, normalize

log = logging.getLogger("ogk.dns")

UPSTREAM_TIMEOUT = 2.0
MAX_CACHE_TTL = 3600
MIN_CACHE_TTL = 0
NEGATIVE_TTL = 60
BLOCK_TTL = 60  # TTL của bản ghi SOA giả không cần thiết; NXDOMAIN của ta không có SOA.


# ---- Bộ nhớ đệm có TTL + LRU ----------------------------------------------------------
@dataclass
class _CacheEntry:
    response: bytes
    ttl_offsets: list[int]
    stored_at: float
    ttl: int


class DnsCache:
    """Cache phản hồi theo khóa (qname, qtype, qclass). Khi trả từ cache:
    vá ID cho khớp truy vấn mới và giảm TTL theo thời gian đã nằm trong cache,
    để client không giữ bản ghi lâu hơn TTL gốc của máy chủ có thẩm quyền."""

    def __init__(self, max_entries: int = 4096, clock: Callable[[], float] = time.monotonic):
        self.max_entries = max_entries
        self._data: OrderedDict[tuple, _CacheEntry] = OrderedDict()
        self._clock = clock
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(q: w.Question) -> tuple:
        return (normalize(q.name), q.qtype, q.qclass)

    def get(self, q: w.Question, query_id: int) -> bytes | None:
        k = self.key(q)
        e = self._data.get(k)
        if e is None:
            self.misses += 1
            return None
        remaining = e.ttl - int(self._clock() - e.stored_at)
        if remaining <= 0:
            del self._data[k]
            self.misses += 1
            return None
        self._data.move_to_end(k)  # LRU: vừa dùng -> đưa về cuối
        self.hits += 1
        pkt = w.patch_id(e.response, query_id)
        return w.patch_ttls(pkt, e.ttl_offsets, remaining)

    def put(self, q: w.Question, response: bytes) -> None:
        try:
            msg = w.parse_message(response)
        except w.DNSParseError:
            return
        if msg.header.tc or msg.header.rcode not in (w.RCODE_NOERROR, w.RCODE_NXDOMAIN):
            return  # không cache gói cắt cụt hay SERVFAIL
        rrs = [r for r in msg.answers + msg.authorities + msg.additionals if r.rtype != w.TYPE_OPT]
        if rrs:
            ttl = min(r.ttl for r in rrs)
        else:
            ttl = NEGATIVE_TTL if msg.header.rcode == w.RCODE_NXDOMAIN else 0
        if msg.header.rcode == w.RCODE_NXDOMAIN:
            ttl = min(ttl, NEGATIVE_TTL)
        ttl = max(MIN_CACHE_TTL, min(ttl, MAX_CACHE_TTL))
        if ttl <= 0:
            return
        k = self.key(q)
        self._data[k] = _CacheEntry(response, [r.ttl_offset for r in rrs], self._clock(), ttl)
        self._data.move_to_end(k)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


# ---- Hỏi upstream -------------------------------------------------------------------
class _OneShotUDP(asyncio.DatagramProtocol):
    def __init__(self, fut: asyncio.Future, expect_id: int, expect_q: w.Question | None):
        self.fut = fut
        self.expect_id = expect_id
        self.expect_q = expect_q

    def datagram_received(self, data: bytes, addr) -> None:
        if self.fut.done() or len(data) < 12:
            return
        # Chỉ nhận gói có đúng ID và đúng question => bỏ qua gói giả mạo/đến muộn.
        if w.get_id(data) != self.expect_id:
            return
        if self.expect_q is not None:
            try:
                m = w.parse_message(data)
            except w.DNSParseError:
                return
            if not m.questions or normalize(m.questions[0].name) != normalize(self.expect_q.name) \
                    or m.questions[0].qtype != self.expect_q.qtype:
                return
        self.fut.set_result(data)

    def error_received(self, exc) -> None:
        if not self.fut.done():
            self.fut.set_exception(exc)


async def udp_exchange(server: tuple[str, int], packet: bytes, timeout: float,
                       expect_q: w.Question | None = None) -> bytes:
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _OneShotUDP(fut, w.get_id(packet), expect_q), remote_addr=server)
    try:
        transport.sendto(packet)
        return await asyncio.wait_for(fut, timeout)
    finally:
        transport.close()


async def tcp_exchange(server: tuple[str, int], packet: bytes, timeout: float) -> bytes:
    """DNS qua TCP (RFC 1035 §4.2.2): mỗi thông điệp có tiền tố độ dài 2 byte."""
    async def _do() -> bytes:
        reader, writer = await asyncio.open_connection(*server)
        try:
            writer.write(struct.pack("!H", len(packet)) + packet)
            await writer.drain()
            (n,) = struct.unpack("!H", await reader.readexactly(2))
            return await reader.readexactly(n)
        finally:
            writer.close()
    return await asyncio.wait_for(_do(), timeout)


class Upstream:
    """Danh sách máy chủ DNS thật (lấy từ cấu hình card mạng trước khi ta đổi sang 127.0.0.1)."""

    def __init__(self, servers: list[tuple[str, int]], timeout: float = UPSTREAM_TIMEOUT,
                 max_inflight: int = 256):
        self.servers = servers
        self.timeout = timeout
        self._sem = asyncio.Semaphore(max_inflight)

    async def resolve(self, packet: bytes, q: w.Question | None = None) -> bytes:
        last_exc: Exception | None = None
        async with self._sem:
            for server in self.servers:
                try:
                    resp = await udp_exchange(server, packet, self.timeout, q)
                    if resp[2] & 0x02:  # bit TC trong byte cờ cao => gói bị cắt, hỏi lại qua TCP
                        resp = await tcp_exchange(server, packet, self.timeout)
                    return resp
                except (asyncio.TimeoutError, OSError, asyncio.IncompleteReadError, struct.error) as exc:
                    last_exc = exc
                    log.debug("upstream %s lỗi: %r", server, exc)
        raise ConnectionError(f"mọi upstream đều lỗi: {last_exc!r}")


# ---- Proxy ------------------------------------------------------------------------------
EventCallback = Callable[[str, w.Question, DnsDecision], None]


class DnsProxy:
    def __init__(self, engine_provider: Callable[[], DnsPolicyEngine], upstream: Upstream,
                 host: str = "127.0.0.1", port: int = 53, on_event: EventCallback | None = None,
                 cache: DnsCache | None = None):
        self.engine_provider = engine_provider
        self.upstream = upstream
        self.host = host
        self.port = port
        self.on_event = on_event or (lambda kind, q, d: None)
        self.cache = cache or DnsCache()
        self._udp_transport = None
        self._tcp_server = None
        self._tasks: set[asyncio.Task] = set()
        self.latencies_ms: list[float] = []  # phục vụ đo M4 (giữ 1000 mẫu gần nhất)
        self.stats = {"queries": 0, "blocked": 0, "safesearch": 0, "servfail": 0, "formerr": 0}

    # -- vòng đời --
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        proxy = self

        class _UDPServer(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                proxy._udp_transport = transport

            def datagram_received(self, data, addr):
                # Mỗi gói một Task: truy vấn chậm không chặn truy vấn khác.
                t = asyncio.ensure_future(proxy._serve_udp(data, addr))
                proxy._tasks.add(t)
                t.add_done_callback(proxy._tasks.discard)

            def error_received(self, exc):
                # Windows: ICMP port unreachable của client cũ có thể dội về dạng lỗi 10054.
                log.debug("UDP error_received: %r", exc)

        await loop.create_datagram_endpoint(_UDPServer, local_addr=(self.host, self.port))
        if self.port == 0:  # cổng ngẫu nhiên (test): lấy cổng thật OS cấp cho UDP rồi mở TCP cùng cổng
            self.port = self._udp_transport.get_extra_info("sockname")[1]
        self._tcp_server = await asyncio.start_server(self._serve_tcp, self.host, self.port)
        log.info("DNS proxy lắng nghe %s:%s (UDP+TCP)", self.host, self.port)

    async def start_on_free_port(self) -> int:
        """Cho test: chọn cổng trống chung cho cả UDP và TCP."""
        import socket
        for _ in range(20):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((self.host, 0))
            port = s.getsockname()[1]
            s.close()
            try:
                self.port = port
                await self.start()
                return port
            except OSError:
                await self.stop()
        raise OSError("không tìm được cổng trống")

    async def stop(self) -> None:
        if self._udp_transport:
            self._udp_transport.close()
            self._udp_transport = None
        if self._tcp_server:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
            self._tcp_server = None
        for t in list(self._tasks):
            t.cancel()

    def flush_cache(self) -> None:
        """Gọi khi chính sách đổi: cache cũ có thể chứa câu trả lời cho miền vừa bị chặn."""
        self.cache.clear()

    # -- phục vụ --
    async def _serve_udp(self, data: bytes, addr) -> None:
        resp = await self.handle(data, transport="udp")
        if resp is not None and self._udp_transport is not None:
            self._udp_transport.sendto(resp, addr)

    async def _serve_tcp(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:  # một kết nối TCP có thể chở nhiều truy vấn liên tiếp
                hdr = await asyncio.wait_for(reader.readexactly(2), timeout=10)
                (n,) = struct.unpack("!H", hdr)
                data = await asyncio.wait_for(reader.readexactly(n), timeout=10)
                resp = await self.handle(data, transport="tcp")
                if resp is None:
                    break
                writer.write(struct.pack("!H", len(resp)) + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    async def handle(self, packet: bytes, transport: str = "udp") -> bytes | None:
        t0 = time.perf_counter()
        self.stats["queries"] += 1
        try:
            query = w.parse_message(packet)
        except w.DNSParseError:
            self.stats["formerr"] += 1
            return w.build_raw_error(packet, w.RCODE_FORMERR)
        if query.header.qr == 1:
            return None  # đây là phản hồi chứ không phải truy vấn: bỏ qua
        if query.header.opcode != 0:
            return w.build_error_response(query, w.RCODE_NOTIMP)
        if len(query.questions) != 1:
            self.stats["formerr"] += 1
            return w.build_error_response(query, w.RCODE_FORMERR)
        q = query.questions[0]
        decision = self.engine_provider().decide(q.name)
        try:
            if decision.action == "block":
                self.stats["blocked"] += 1
                resp = w.build_error_response(query, w.RCODE_NXDOMAIN)
                self._emit("blocked", q, decision)
            elif decision.action == "safesearch":
                self.stats["safesearch"] += 1
                resp = await self._safesearch(query, q, decision.cname_target)
                self._emit("query", q, decision)
            else:
                resp = self.cache.get(q, query.header.id)
                if resp is None:
                    resp = await self.upstream.resolve(packet, q)
                    self.cache.put(q, resp)
                self._emit("query", q, decision)
        except Exception as exc:  # upstream chết/timeout -> SERVFAIL thay vì im lặng
            log.debug("SERVFAIL cho %s: %r", q.name, exc)
            self.stats["servfail"] += 1
            resp = w.build_error_response(query, w.RCODE_SERVFAIL)
        # Gói vượt giới hạn UDP của client => trả TC=1 để client hỏi lại qua TCP.
        if transport == "udp" and len(resp) > query.edns_udp_size:
            resp = w.build_truncated(query)
        self._record_latency((time.perf_counter() - t0) * 1000)
        return resp

    async def _safesearch(self, query: w.Message, q: w.Question, target: str) -> bytes:
        """Trả CNAME (tên gốc -> forcesafesearch...) + bản ghi A/AAAA của đích, tra động.

        Với qtype khác A/AAAA (vd HTTPS=65), chỉ trả CNAME: client sẽ tự đi theo CNAME.
        """
        answers: list[tuple[str | None, int, int, bytes]] = [(None, w.TYPE_CNAME, 300, w.cname_rdata(target))]
        if q.qtype in (w.TYPE_A, w.TYPE_AAAA):
            sub_q = w.Question(target, q.qtype)
            cached = self.cache.get(sub_q, 0)
            raw = cached
            if raw is None:
                raw = await self.upstream.resolve(w.build_query(target, q.qtype, qid=int.from_bytes(os.urandom(2), "big")), sub_q)
                self.cache.put(sub_q, raw)
            sub = w.parse_message(raw)
            for rr in sub.answers:
                if rr.rtype == q.qtype:
                    answers.append((target, rr.rtype, min(rr.ttl, 300), rr.rdata))
        return w.build_answer_response(query, answers)

    def _emit(self, kind: str, q: w.Question, decision: DnsDecision) -> None:
        try:
            self.on_event(kind, q, decision)
        except Exception:  # callback lỗi không được làm hỏng phản hồi DNS
            log.exception("on_event lỗi")

    def _record_latency(self, ms: float) -> None:
        self.latencies_ms.append(ms)
        if len(self.latencies_ms) > 1000:
            del self.latencies_ms[:500]


def flush_windows_dns_cache() -> bool:
    """Xóa cache DNS của Windows (tương đương `ipconfig /flushdns`) khi chính sách đổi."""
    import sys
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.dnsapi.DnsFlushResolverCache())
    except Exception:
        return False
