"""Unit test: mã hóa/giải mã gói DNS (RFC 1035), nén con trỏ, chống vòng lặp, NXDOMAIN giữ ID."""
import struct

import pytest

from agent import dns_wire as w


def test_encode_decode_roundtrip():
    pkt = w.build_query("www.Example.com", w.TYPE_A, qid=0xBEEF)
    msg = w.parse_message(pkt)
    assert msg.header.id == 0xBEEF
    assert msg.header.rd == 1
    assert msg.questions[0].name == "www.Example.com"
    assert msg.questions[0].qtype == w.TYPE_A


def test_compression_pointer_is_followed():
    # Answer dùng con trỏ 0xC00C trỏ về QNAME tại offset 12
    q = w.parse_message(w.build_query("example.org", w.TYPE_A, qid=7))
    resp = w.build_answer_response(q, [(None, w.TYPE_A, 300, w.a_rdata("93.184.216.34"))])
    assert b"\xc0\x0c" in resp
    m = w.parse_message(resp)
    assert m.answers[0].name == "example.org"
    assert m.answers[0].value == "93.184.216.34"
    assert m.answers[0].ttl == 300


def test_pointer_loop_is_rejected():
    # Header 1 question, QNAME tại offset 12 là con trỏ trỏ vào CHÍNH NÓ (0xC00C) -> vòng lặp vô hạn
    pkt = struct.pack("!HHHHHH", 1, 0, 1, 0, 0, 0) + b"\xc0\x0c" + struct.pack("!HH", 1, 1)
    with pytest.raises(w.DNSParseError):
        w.parse_message(pkt)


def test_forward_pointer_is_rejected():
    # Con trỏ trỏ TỚI (offset 20 > vị trí 12) cũng bị từ chối
    pkt = struct.pack("!HHHHHH", 1, 0, 1, 0, 0, 0) + b"\xc0\x14" + struct.pack("!HH", 1, 1) + b"\x00" * 8
    with pytest.raises(w.DNSParseError):
        w.parse_message(pkt)


def test_truncated_packet_rejected():
    pkt = w.build_query("example.com")[:-3]
    with pytest.raises(w.DNSParseError):
        w.parse_message(pkt)


def test_nxdomain_keeps_id_and_question():
    q = w.parse_message(w.build_query("blocked.example", w.TYPE_AAAA, qid=0x1234))
    resp = w.parse_message(w.build_error_response(q, w.RCODE_NXDOMAIN))
    assert resp.header.id == 0x1234
    assert resp.header.qr == 1
    assert resp.header.rcode == w.RCODE_NXDOMAIN
    assert resp.header.rd == 1
    assert resp.questions[0].name == "blocked.example"
    assert resp.questions[0].qtype == w.TYPE_AAAA


def test_patch_ttl_and_id():
    q = w.parse_message(w.build_query("example.net", qid=1))
    resp = w.build_answer_response(q, [(None, w.TYPE_A, 300, w.a_rdata("10.0.0.1"))])
    m = w.parse_message(resp)
    patched = w.patch_ttls(w.patch_id(resp, 99), [m.answers[0].ttl_offset], 42)
    m2 = w.parse_message(patched)
    assert m2.header.id == 99 and m2.answers[0].ttl == 42


def test_label_too_long():
    with pytest.raises(ValueError):
        w.encode_name("a" * 64 + ".com")
