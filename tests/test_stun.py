"""Tests for the bundled STUN server (minimost.stun)."""

import socket
import struct
import threading
import time

from minimost import stun

_MAGIC = 0x2112A442


def _binding_request(txid=b"\x00" * 12):
    return struct.pack(">HHI", 0x0001, 0, _MAGIC) + txid


def _decode_xor_mapped_address(resp):
    """Return (ip, port) decoded from a Binding Success Response."""
    msg_type, _length, magic = struct.unpack(">HHI", resp[:8])
    assert msg_type == 0x0101
    assert magic == _MAGIC
    txid = resp[8:20]
    attr_type, attr_len = struct.unpack(">HH", resp[20:24])
    assert attr_type == 0x0020
    _, _family, x_port, x_addr = struct.unpack(">BBHI", resp[24 : 24 + attr_len])
    ip = socket.inet_ntoa(struct.pack(">I", x_addr ^ _MAGIC))
    port = x_port ^ (_MAGIC >> 16)
    return ip, port, txid


def test_build_response_decodes_to_source_address():
    txid = b"abcdef012345"
    resp = stun.build_binding_response(_binding_request(txid), ("192.168.1.50", 54321))
    ip, port, got_txid = _decode_xor_mapped_address(resp)
    assert ip == "192.168.1.50"
    assert port == 54321
    assert got_txid == txid


def test_build_response_rejects_short_datagram():
    assert stun.build_binding_response(b"\x00" * 4, ("127.0.0.1", 1)) is None


def test_build_response_rejects_wrong_magic_cookie():
    bad = struct.pack(">HHI", 0x0001, 0, 0xDEADBEEF) + b"\x00" * 12
    assert stun.build_binding_response(bad, ("127.0.0.1", 1)) is None


def test_build_response_rejects_non_binding_request():
    # 0x0101 is a Binding *Response*, not a request — must be ignored.
    other = struct.pack(">HHI", 0x0101, 0, _MAGIC) + b"\x00" * 12
    assert stun.build_binding_response(other, ("127.0.0.1", 1)) is None


def test_build_response_rejects_bad_ip():
    assert stun.build_binding_response(_binding_request(), ("not-an-ip", 1)) is None


def test_server_answers_over_udp():
    # Drive the serving loop directly in a daemon thread rather than via
    # start_stun_server(): that helper is idempotent per process, so once any
    # create_app() in the wider suite has started the server, a second call here
    # would be a no-op and nothing would bind this port.
    thread = threading.Thread(
        target=stun._serve_forever, args=("127.0.0.1", 53998), daemon=True
    )
    thread.start()
    time.sleep(0.3)
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(2)
    try:
        client.sendto(_binding_request(), ("127.0.0.1", 53998))
        data, _ = client.recvfrom(2048)
    finally:
        client.close()
    ip, port, _ = _decode_xor_mapped_address(data)
    assert ip == "127.0.0.1"
    assert port > 0


def test_start_is_idempotent():
    # Already started above; a second call must be a no-op and not raise.
    stun.start_stun_server(port=53997, host="127.0.0.1")
    stun.start_stun_server(port=53997, host="127.0.0.1")
