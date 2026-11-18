"""
agent/dns_wire.py — Đọc/ghi gói tin DNS theo RFC 1035, viết tay, không dùng thư viện ngoài.

Yêu cầu đề: F2 (DNS proxy 127.0.0.1:53, NXDOMAIN giữ đúng ID, SafeSearch bằng CNAME), M1.

Cấu trúc một gói DNS (cả truy vấn lẫn phản hồi đều cùng định dạng):

    +---------------------+
    |       Header        |  12 byte cố định: ID, FLAGS, QDCOUNT, ANCOUNT, NSCOUNT, ARCOUNT
    +---------------------+
    |      Question       |  QNAME (chuỗi nhãn) + QTYPE (2B) + QCLASS (2B)
    +---------------------+
    |       Answer        |  các bản ghi tài nguyên (RR)
    +---------------------+
    |      Authority      |  RR (ví dụ SOA khi NXDOMAIN)
    +---------------------+
    |      Additional     |  RR (ví dụ OPT của EDNS0)
    +---------------------+

Mỗi RR: NAME + TYPE(2) + CLASS(2) + TTL(4) + RDLENGTH(2) + RDATA(RDLENGTH).

Tên miền mã hóa dạng chuỗi nhãn có tiền tố độ dài: "www.example.com" ->
    03 'www' 07 'example' 03 'com' 00
Để tiết kiệm chỗ, RFC 1035 §4.1.4 cho phép NÉN TÊN: hai bit cao 11 nghĩa là
"con trỏ 14 bit" trỏ về một vị trí trước đó trong gói (ví dụ 0xC00C trỏ về
QNAME ở offset 12). Kẻ tấn công có thể dựng con trỏ trỏ vòng (A->B->A) để
treo bộ phân tích => ta chặn bằng 2 điều kiện: con trỏ phải trỏ LÙI và
tổng số lần nhảy <= MAX_POINTER_JUMPS.
"""
from __future__ import annotations

import ipaddress
import struct
from dataclasses import dataclass, field

# ---- Hằng số giao thức -------------------------------------------------------
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_PTR = 12
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33
TYPE_OPT = 41  # EDNS0 (RFC 6891)
TYPE_SVCB = 64
TYPE_HTTPS = 65
CLASS_IN = 1

RCODE_NOERROR = 0
RCODE_FORMERR = 1
RCODE_SERVFAIL = 2
RCODE_NXDOMAIN = 3
RCODE_NOTIMP = 4
RCODE_REFUSED = 5

# Bit cờ trong trường FLAGS (16 bit):  QR | OPCODE(4) | AA | TC | RD | RA | Z(3) | RCODE(4)
FLAG_QR = 0x8000
FLAG_AA = 0x0400
FLAG_TC = 0x0200
FLAG_RD = 0x0100
FLAG_RA = 0x0080

HEADER = struct.Struct("!HHHHHH")  # 6 số nguyên 16 bit big-endian (network byte order)
MAX_POINTER_JUMPS = 16
MAX_NAME_LEN = 255
MAX_LABEL_LEN = 63
UDP_DEFAULT_LIMIT = 512  # RFC 1035: gói UDP không có EDNS tối đa 512 byte


class DNSParseError(ValueError):
    """Gói tin sai định dạng (cắt cụt, con trỏ vòng, nhãn quá dài...)."""


@dataclass
class Header:
    id: int
    flags: int
    qdcount: int
    ancount: int
    nscount: int
    arcount: int

    @property
    def qr(self) -> int:
        return (self.flags >> 15) & 1

    @property
    def opcode(self) -> int:
        return (self.flags >> 11) & 0xF

    @property
    def tc(self) -> int:
        return (self.flags >> 9) & 1

    @property
    def rd(self) -> int:
        return (self.flags >> 8) & 1

    @property
    def rcode(self) -> int:
        return self.flags & 0xF


@dataclass
class Question:
    name: str
    qtype: int
    qclass: int = CLASS_IN


@dataclass
class ResourceRecord:
    name: str
    rtype: int
    rclass: int
    ttl: int
    rdata: bytes
    ttl_offset: int = -1  # vị trí trường TTL trong gói gốc (để vá TTL khi trả từ cache)
    value: str | None = None  # giá trị đã giải mã cho A/AAAA/CNAME (để log/test)


@dataclass
class Message:
    header: Header
    questions: list[Question] = field(default_factory=list)
    answers: list[ResourceRecord] = field(default_factory=list)
    authorities: list[ResourceRecord] = field(default_factory=list)
    additionals: list[ResourceRecord] = field(default_factory=list)

    @property
    def edns_udp_size(self) -> int:
        """Kích thước UDP tối đa client chấp nhận (trường CLASS của bản ghi OPT)."""
        for rr in self.additionals:
            if rr.rtype == TYPE_OPT:
                return max(UDP_DEFAULT_LIMIT, rr.rclass)
        return UDP_DEFAULT_LIMIT


# ---- Đọc tên miền (có xử lý nén con trỏ) ----------------------------------------
def read_name(buf: bytes, offset: int) -> tuple[str, int]:
    """Đọc một tên miền bắt đầu tại offset. Trả (tên, offset ngay sau tên trong luồng chính)."""
    labels: list[str] = []
    jumps = 0
    end_offset: int | None = None  # vị trí kết thúc trong luồng chính (trước lần nhảy đầu tiên)
    total_len = 0
    pos = offset
    while True:
        if pos >= len(buf):
            raise DNSParseError("tên miền bị cắt cụt")
        length = buf[pos]
        tag = length & 0xC0
        if tag == 0xC0:
            # Con trỏ nén: 2 byte, 14 bit thấp là offset tuyệt đối trong gói.
            if pos + 1 >= len(buf):
                raise DNSParseError("con trỏ bị cắt cụt")
            ptr = ((length & 0x3F) << 8) | buf[pos + 1]
            if end_offset is None:
                end_offset = pos + 2
            jumps += 1
            # Chống vòng lặp: (1) chỉ cho phép trỏ LÙI về dữ liệu đã xuất hiện,
            # (2) giới hạn số lần nhảy. Một trong hai đã đủ, dùng cả hai cho chắc.
            if ptr >= pos or jumps > MAX_POINTER_JUMPS:
                raise DNSParseError("phát hiện con trỏ nén vòng lặp/không hợp lệ")
            pos = ptr
            continue
        if tag != 0:
            raise DNSParseError("kiểu nhãn không hỗ trợ (0x40/0x80)")
        if length == 0:
            pos += 1
            break
        if length > MAX_LABEL_LEN:
            raise DNSParseError("nhãn dài hơn 63 byte")
        start, stop = pos + 1, pos + 1 + length
        if stop > len(buf):
            raise DNSParseError("nhãn bị cắt cụt")
        total_len += length + 1
        if total_len > MAX_NAME_LEN:
            raise DNSParseError("tên miền dài hơn 255 byte")
        # latin-1 không bao giờ lỗi giải mã; tên quốc tế đã ở dạng punycode ASCII (xn--...)
        labels.append(buf[start:stop].decode("latin-1"))
        pos = stop
    return ".".join(labels), (end_offset if end_offset is not None else pos)


def encode_name(name: str) -> bytes:
    """Mã hóa tên miền thành chuỗi nhãn (không nén)."""
    name = name.rstrip(".")
    if not name:
        return b"\x00"
    out = bytearray()
    for label in name.split("."):
        raw = label.encode("idna") if any(ord(c) > 127 for c in label) else label.encode("ascii")
        if not 0 < len(raw) <= MAX_LABEL_LEN:
            raise ValueError(f"nhãn không hợp lệ: {label!r}")
        out.append(len(raw))
        out += raw
    out.append(0)
    if len(out) > MAX_NAME_LEN:
        raise ValueError("tên miền quá dài")
    return bytes(out)


# ---- Phân tích gói ----------------------------------------------------------------
def _read_rr(buf: bytes, offset: int) -> tuple[ResourceRecord, int]:
    name, offset = read_name(buf, offset)
    if offset + 10 > len(buf):
        raise DNSParseError("RR bị cắt cụt")
    rtype, rclass, ttl, rdlen = struct.unpack_from("!HHIH", buf, offset)
    ttl_offset = offset + 4
    offset += 10
    if offset + rdlen > len(buf):
        raise DNSParseError("RDATA bị cắt cụt")
    rdata = buf[offset:offset + rdlen]
    value = None
    if rtype == TYPE_A and rdlen == 4:
        value = str(ipaddress.IPv4Address(rdata))
    elif rtype == TYPE_AAAA and rdlen == 16:
        value = str(ipaddress.IPv6Address(rdata))
    elif rtype == TYPE_CNAME:
        value, _ = read_name(buf, offset)  # RDATA của CNAME có thể chứa con trỏ nén
    rr = ResourceRecord(name, rtype, rclass, ttl, rdata, ttl_offset, value)
    return rr, offset + rdlen


def parse_message(buf: bytes) -> Message:
    if len(buf) < HEADER.size:
        raise DNSParseError("gói ngắn hơn 12 byte header")
    header = Header(*HEADER.unpack_from(buf, 0))
    offset = HEADER.size
    msg = Message(header)
    if header.qdcount > 16 or header.ancount + header.nscount + header.arcount > 512:
        raise DNSParseError("số lượng bản ghi bất thường")
    for _ in range(header.qdcount):
        name, offset = read_name(buf, offset)
        if offset + 4 > len(buf):
            raise DNSParseError("question bị cắt cụt")
        qtype, qclass = struct.unpack_from("!HH", buf, offset)
        offset += 4
        msg.questions.append(Question(name, qtype, qclass))
    for count, bucket in ((header.ancount, msg.answers),
                          (header.nscount, msg.authorities),
                          (header.arcount, msg.additionals)):
        for _ in range(count):
            rr, offset = _read_rr(buf, offset)
            bucket.append(rr)
    return msg


# ---- Dựng gói ----------------------------------------------------------------------
def build_query(name: str, qtype: int = TYPE_A, qid: int = 0, rd: bool = True) -> bytes:
    flags = FLAG_RD if rd else 0
    return HEADER.pack(qid, flags, 1, 0, 0, 0) + encode_name(name) + struct.pack("!HH", qtype, CLASS_IN)


def _question_bytes(q: Question) -> bytes:
    return encode_name(q.name) + struct.pack("!HH", q.qtype, q.qclass)


def _response_flags(query: Message, rcode: int, tc: bool = False) -> int:
    # QR=1 (đây là phản hồi), giữ nguyên OPCODE và RD của truy vấn, RA=1 (ta hỗ trợ đệ quy)
    flags = FLAG_QR | (query.header.flags & 0x7800) | (query.header.flags & FLAG_RD) | FLAG_RA
    if tc:
        flags |= FLAG_TC
    return flags | (rcode & 0xF)


def build_error_response(query: Message, rcode: int) -> bytes:
    """Phản hồi lỗi (NXDOMAIN/SERVFAIL/REFUSED...) giữ ĐÚNG ID và echo lại question.

    Giữ đúng ID là bắt buộc: stub resolver của Windows ghép phản hồi với truy vấn
    bằng (ID, cổng nguồn, question). Sai ID => client bỏ qua gói và chờ tới timeout.
    """
    qd = query.questions[:1]
    body = b"".join(_question_bytes(q) for q in qd)
    return HEADER.pack(query.header.id, _response_flags(query, rcode), len(qd), 0, 0, 0) + body


def build_raw_error(packet: bytes, rcode: int) -> bytes | None:
    """Dùng khi không phân tích nổi gói: chỉ cần 2 byte ID là đủ để trả FORMERR."""
    if len(packet) < 2:
        return None
    qid = struct.unpack_from("!H", packet, 0)[0]
    return HEADER.pack(qid, FLAG_QR | FLAG_RA | (rcode & 0xF), 0, 0, 0, 0)


def build_truncated(query: Message) -> bytes:
    """Gói rỗng có cờ TC=1: báo client "gói quá lớn cho UDP, hãy hỏi lại qua TCP"."""
    qd = query.questions[:1]
    body = b"".join(_question_bytes(q) for q in qd)
    return HEADER.pack(query.header.id, _response_flags(query, RCODE_NOERROR, tc=True), len(qd), 0, 0, 0) + body


def rr_bytes(owner: bytes, rtype: int, ttl: int, rdata: bytes, rclass: int = CLASS_IN) -> bytes:
    return owner + struct.pack("!HHIH", rtype, rclass, ttl, len(rdata)) + rdata


def build_answer_response(query: Message, answers: list[tuple[str | None, int, int, bytes]]) -> bytes:
    """Dựng phản hồi NOERROR với danh sách (owner, type, ttl, rdata).

    owner=None nghĩa là "tên trong question" => dùng con trỏ nén 0xC00C (offset 12,
    ngay sau header) thay vì viết lại cả tên: minh họa trực tiếp kỹ thuật nén RFC 1035.
    """
    q = query.questions[0]
    body = bytearray(_question_bytes(q))
    for owner, rtype, ttl, rdata in answers:
        owner_bytes = b"\xc0\x0c" if owner is None else encode_name(owner)
        body += rr_bytes(owner_bytes, rtype, ttl, rdata)
    head = HEADER.pack(query.header.id, _response_flags(query, RCODE_NOERROR), 1, len(answers), 0, 0)
    return head + bytes(body)


def cname_rdata(target: str) -> bytes:
    return encode_name(target)


def a_rdata(ip: str) -> bytes:
    return ipaddress.ip_address(ip).packed


# ---- Tiện ích thao tác trên byte (dùng cho cache) --------------------------------
def patch_id(packet: bytes, new_id: int) -> bytes:
    """Thay 2 byte ID đầu gói (cache lưu phản hồi của truy vấn cũ, ID phải khớp truy vấn mới)."""
    return struct.pack("!H", new_id) + packet[2:]


def patch_ttls(packet: bytes, ttl_offsets: list[int], new_ttl: int) -> bytes:
    """Ghi đè TTL tại các offset đã biết (TTL còn lại = TTL gốc - thời gian đã nằm trong cache)."""
    buf = bytearray(packet)
    for off in ttl_offsets:
        struct.pack_into("!I", buf, off, max(0, new_ttl))
    return bytes(buf)


def get_id(packet: bytes) -> int:
    return struct.unpack_from("!H", packet, 0)[0]
