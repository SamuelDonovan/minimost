"""
minimost.stun
=============

A minimal, dependency-free STUN server (RFC 5389) used purely so that WebRTC
peers on the LAN gather a **server-reflexive** ICE candidate carrying their real
LAN IP address.

Why this exists
---------------
Browsers hide a machine's real LAN IP behind a random ``<uuid>.local`` mDNS
*host* candidate by default.  On a LAN without a working mDNS responder
(avahi/Bonjour) the remote peer cannot resolve that name, every candidate pair
is unusable, and the connection fails with ``ICE failed`` (a black screen for
screen shares).

Pointing the browser at a STUN server makes it additionally gather a
*server-reflexive* candidate — and unlike host candidates, srflx candidates are
**not** mDNS-obfuscated: they contain the real address the STUN server observed.
Because MiniMost is LAN-only there is no NAT between peers, so the reflexed
address is directly reachable and the connection succeeds with **zero extra
configuration** — no avahi, no browser flags, no public STUN server (so it works
even air-gapped).

This server answers only Binding Requests with a Binding Success Response
carrying an ``XOR-MAPPED-ADDRESS`` attribute, which is all browsers need for
candidate gathering.  It does not implement authentication or the full
connectivity-check machinery (those happen peer-to-peer, not against this
server).

Module-level attributes
-----------------------
DEFAULT_STUN_PORT : int
    The default UDP port (3478, the IANA-assigned STUN port).
"""

import socket
import struct
import threading

DEFAULT_STUN_PORT = 3478

# Bind all interfaces: the STUN server must be reachable by every peer on the
# LAN, so listening only on loopback would defeat its purpose.
_BIND_ALL = "0.0.0.0"  # nosec B104

_MAGIC_COOKIE = 0x2112A442
_BINDING_REQUEST = 0x0001
_BINDING_SUCCESS = 0x0101
_ATTR_XOR_MAPPED_ADDRESS = 0x0020
_FAMILY_IPV4 = 0x01

_started_lock = threading.Lock()
_started = False


def build_binding_response(data: bytes, addr: tuple) -> bytes | None:
    """Build a Binding Success Response for a STUN Binding Request.

    :param data: The raw datagram received from the client.
    :type data: bytes
    :param addr: The ``(ip, port)`` the datagram was received from.
    :type addr: tuple
    :returns: The response datagram, or ``None`` if *data* is not a valid
        Binding Request this server should answer.
    :rtype: bytes or None
    """
    if len(data) < 20:
        return None
    msg_type, _, magic = struct.unpack(">HHI", data[:8])
    if msg_type != _BINDING_REQUEST or magic != _MAGIC_COOKIE:
        return None

    transaction_id = data[8:20]
    ip, port = addr[0], addr[1]

    try:
        ip_int = struct.unpack(">I", socket.inet_aton(ip))[0]
    except OSError:
        return None

    # XOR the address/port with the magic cookie per RFC 5389 §15.2.
    x_port = port ^ (_MAGIC_COOKIE >> 16)
    x_addr = ip_int ^ _MAGIC_COOKIE
    value = struct.pack(">BBHI", 0, _FAMILY_IPV4, x_port, x_addr)
    attribute = struct.pack(">HH", _ATTR_XOR_MAPPED_ADDRESS, len(value)) + value

    header = struct.pack(">HHI", _BINDING_SUCCESS, len(attribute), _MAGIC_COOKIE)
    return header + transaction_id + attribute


def _serve_forever(host: str, port: int) -> None:
    """Bind a UDP socket and answer STUN Binding Requests forever."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # SO_REUSEPORT lets every gunicorn worker bind the same port and share the
    # load; on platforms without it, only the first binder wins and the rest
    # raise OSError below (harmless — another process owns the server).
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        return

    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except OSError:
            continue
        response = build_binding_response(data, addr)
        if response:
            try:
                sock.sendto(response, addr)
            except (
                OSError
            ):  # nosec B110 — best-effort; a dropped reply is retried by ICE
                pass


def start_stun_server(port: int = DEFAULT_STUN_PORT, host: str = _BIND_ALL) -> None:
    """Start the STUN server in a daemon thread (idempotent within a process).

    Safe to call from :func:`minimost.create_app`.  The thread is a daemon, so
    it exits automatically when the process shuts down.  Binding ``0.0.0.0`` is
    intentional: the server must be reachable by every peer on the LAN.

    :param port: UDP port to listen on.  Defaults to :data:`DEFAULT_STUN_PORT`.
    :param host: Interface to bind.  Defaults to all interfaces.
    """
    global _started
    with _started_lock:
        if _started:
            return
        _started = True
    thread = threading.Thread(
        target=_serve_forever, args=(host, port), daemon=True, name="minimost-stun"
    )
    thread.start()
