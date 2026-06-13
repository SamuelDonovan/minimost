"""
minimost._pki
=============

A tiny, dependency-free public-key infrastructure toolkit: just enough RSA,
DER/ASN.1 and X.509 to mint the local CA and the TLS leaf certificate MiniMost
serves, using **only the Python standard library**.

Historically :mod:`minimost.certs` shelled out to the system ``openssl`` binary
to do this.  That binary is absent by default on Windows (and on stripped-down
containers), which silently downgraded MiniMost to plain HTTP and broke calls.
This module removes that external requirement.

Scope is deliberately narrow — it is *not* a general crypto library:

* RSA key generation, PKCS#1 v1.5 signing/verification (SHA-256 only).
* A minimal DER encoder (the handful of ASN.1 types X.509 needs) and an equally
  small reader used for renewal checks (reading ``notAfter`` and verifying that
  a leaf still chains to the current CA).
* :func:`build_ca_cert` / :func:`build_leaf_cert` assemble the exact certificate
  shape Chrome validates: v3, a SAN, ``basicConstraints``/``keyUsage`` and (for
  the leaf) ``extendedKeyUsage = serverAuth``.

The cryptography here is intended for a LAN-local, self-managed trust anchor, not
for adversarial settings; key sizes and primality confidence are chosen
accordingly.  All functions operate on ``bytes``/``str`` and never touch the
filesystem — that is :mod:`minimost.certs`'s job — which keeps them easy to test.
"""

import base64
import datetime
import hashlib
import secrets
from typing import Dict, List, Tuple

# --------------------------------------------------------------------------
# Object identifiers used by the certificates we build.
# --------------------------------------------------------------------------
_OID_RSA_ENCRYPTION = "1.2.840.113549.1.1.1"
_OID_SHA256_WITH_RSA = "1.2.840.113549.1.1.11"
_OID_SHA256 = "2.16.840.1.101.3.4.2.1"
_OID_COMMON_NAME = "2.5.4.3"
_OID_SUBJECT_ALT_NAME = "2.5.29.17"
_OID_BASIC_CONSTRAINTS = "2.5.29.19"
_OID_KEY_USAGE = "2.5.29.15"
_OID_EXT_KEY_USAGE = "2.5.29.37"
_OID_SERVER_AUTH = "1.3.6.1.5.5.7.3.1"
_OID_SUBJECT_KEY_ID = "2.5.29.14"
_OID_AUTHORITY_KEY_ID = "2.5.29.35"

# keyUsage bit positions (bit 0 is the most-significant bit of the first byte).
_KU_DIGITAL_SIGNATURE = 0
_KU_KEY_ENCIPHERMENT = 2
_KU_KEY_CERT_SIGN = 5
_KU_CRL_SIGN = 6

# Small primes for cheap trial division before the (more expensive)
# Miller-Rabin test during prime search.
_SMALL_PRIMES = [
    2,
    3,
    5,
    7,
    11,
    13,
    17,
    19,
    23,
    29,
    31,
    37,
    41,
    43,
    47,
    53,
    59,
    61,
    67,
    71,
    73,
    79,
    83,
    89,
    97,
    101,
    103,
    107,
    109,
    113,
    127,
    131,
    137,
    139,
    149,
    151,
    157,
    163,
    167,
    173,
    179,
    181,
    191,
    193,
    197,
    199,
    211,
    223,
    227,
    229,
    233,
    239,
    241,
    251,
]


# ==========================================================================
# DER / ASN.1 encoding
# ==========================================================================
def _der_len(length: int) -> bytes:
    """Encode a DER length using the definite short/long form."""
    if length < 0x80:
        return bytes([length])
    body = bytearray()
    while length:
        body.insert(0, length & 0xFF)
        length >>= 8
    return bytes([0x80 | len(body)]) + bytes(body)


def _tlv(tag: int, value: bytes) -> bytes:
    """Wrap *value* in a DER tag-length-value triple."""
    return bytes([tag]) + _der_len(len(value)) + value


def _der_int(value: int) -> bytes:
    """Encode a non-negative integer as a DER INTEGER (always positive)."""
    if value == 0:
        body = b"\x00"
    else:
        body = value.to_bytes((value.bit_length() + 7) // 8, "big")
        # A leading high bit would mark the integer negative in DER, so pad it.
        if body[0] & 0x80:
            body = b"\x00" + body
    return _tlv(0x02, body)


def _der_seq(*items: bytes) -> bytes:
    return _tlv(0x30, b"".join(items))


def _der_set(*items: bytes) -> bytes:
    return _tlv(0x31, b"".join(items))


def _der_oid(oid: str) -> bytes:
    """Encode a dotted OID string as a DER OBJECT IDENTIFIER."""
    parts = [int(p) for p in oid.split(".")]
    body = bytearray([40 * parts[0] + parts[1]])
    for number in parts[2:]:
        chunk = bytearray([number & 0x7F])
        number >>= 7
        while number:
            chunk.insert(0, (number & 0x7F) | 0x80)
            number >>= 7
        body.extend(chunk)
    return _tlv(0x06, bytes(body))


def _der_null() -> bytes:
    return _tlv(0x05, b"")


def _der_bool(value: bool) -> bytes:
    return _tlv(0x01, b"\xff" if value else b"\x00")


def _der_octet_string(value: bytes) -> bytes:
    return _tlv(0x04, value)


def _der_bit_string(value: bytes, unused_bits: int = 0) -> bytes:
    return _tlv(0x03, bytes([unused_bits]) + value)


def _der_utf8(value: str) -> bytes:
    return _tlv(0x0C, value.encode("utf-8"))


def _der_explicit(tag_number: int, value: bytes) -> bytes:
    """Wrap *value* in an explicit (constructed) context-specific tag."""
    return _tlv(0xA0 | tag_number, value)


def _der_implicit(tag_number: int, value: bytes) -> bytes:
    """Wrap *value* in an implicit (primitive) context-specific tag."""
    return _tlv(0x80 | tag_number, value)


def _algorithm_identifier(oid: str) -> bytes:
    """An AlgorithmIdentifier with a NULL parameter (RSA/SHA-256 convention)."""
    return _der_seq(_der_oid(oid), _der_null())


def _name(common_name: str) -> bytes:
    """Encode an X.501 Name carrying a single CN RDN."""
    attribute = _der_seq(_der_oid(_OID_COMMON_NAME), _der_utf8(common_name))
    return _der_seq(_der_set(attribute))


def _encode_time(when: datetime.datetime) -> bytes:
    """Encode a UTC datetime as UTCTime (<2050) or GeneralizedTime (>=2050)."""
    if when.year < 2050:
        return _tlv(0x17, when.strftime("%y%m%d%H%M%SZ").encode("ascii"))
    return _tlv(0x18, when.strftime("%Y%m%d%H%M%SZ").encode("ascii"))


# ==========================================================================
# RSA
# ==========================================================================
def _is_probable_prime(candidate: int, rounds: int = 20) -> bool:
    """Miller-Rabin primality test, preceded by small-prime trial division."""
    if candidate < 2:
        return False
    for prime in _SMALL_PRIMES:
        if candidate % prime == 0:
            return candidate == prime
    # Write candidate-1 as d * 2**r with d odd.
    d = candidate - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        witness = secrets.randbelow(candidate - 3) + 2
        x = pow(witness, d, candidate)
        if x == 1 or x == candidate - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, candidate)
            if x == candidate - 1:
                break
        else:
            return False
    return True


def _generate_prime(bits: int) -> int:
    """Return a random probable prime with the top and bottom bits set."""
    while True:
        candidate = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


def _modinv(a: int, modulus: int) -> int:
    """Modular inverse via the iterative extended Euclidean algorithm.

    Used instead of ``pow(a, -1, modulus)`` so the module stays importable on
    Python 3.6/3.7 (three-argument ``pow`` with a negative exponent is 3.8+).
    """
    old_r, r = a, modulus
    old_s, s = 1, 0
    while r != 0:
        quotient = old_r // r
        old_r, r = r, old_r - quotient * r
        old_s, s = s, old_s - quotient * s
    if old_r != 1:
        raise ValueError("value is not invertible")
    return old_s % modulus


def generate_key(bits: int = 2048) -> Dict[str, int]:
    """Generate an RSA private key.

    :param bits: Modulus size in bits.  Defaults to 2048.
    :returns: A dict with the key components ``n, e, d, p, q``.
    :rtype: dict
    """
    public_exponent = 65537
    half = bits // 2
    while True:
        p = _generate_prime(half)
        q = _generate_prime(half)
        if p == q:
            continue
        modulus = p * q
        if modulus.bit_length() != bits:
            continue
        totient = (p - 1) * (q - 1)
        if totient % public_exponent == 0:
            continue
        private_exponent = _modinv(public_exponent, totient)
        return {
            "n": modulus,
            "e": public_exponent,
            "d": private_exponent,
            "p": p,
            "q": q,
        }


def _public_key(key: Dict[str, int]) -> Dict[str, int]:
    return {"n": key["n"], "e": key["e"]}


def _pkcs1_digest_info(message: bytes) -> bytes:
    """Build the DER DigestInfo (SHA-256) for *message*."""
    digest = hashlib.sha256(message).digest()
    return _der_seq(_algorithm_identifier(_OID_SHA256), _der_octet_string(digest))


def _pkcs1_pad(message: bytes, key_bytes: int) -> bytes:
    """Apply EMSA-PKCS1-v1_5 padding to a SHA-256 DigestInfo of *message*."""
    digest_info = _pkcs1_digest_info(message)
    padding_len = key_bytes - len(digest_info) - 3
    if padding_len < 8:
        raise ValueError("RSA key too small for PKCS#1 v1.5 signature")
    return b"\x00\x01" + b"\xff" * padding_len + b"\x00" + digest_info


def sign(key: Dict[str, int], message: bytes) -> bytes:
    """RSASSA-PKCS1-v1_5 sign *message* with SHA-256 under the private *key*."""
    key_bytes = (key["n"].bit_length() + 7) // 8
    encoded = _pkcs1_pad(message, key_bytes)
    signature_int = pow(int.from_bytes(encoded, "big"), key["d"], key["n"])
    return signature_int.to_bytes(key_bytes, "big")


def _verify(public: Dict[str, int], message: bytes, signature: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 verify (SHA-256) — constant-time-ness is unnecessary
    here because this only validates our own freshly read certificate."""
    key_bytes = (public["n"].bit_length() + 7) // 8
    if len(signature) != key_bytes:
        return False
    recovered = pow(int.from_bytes(signature, "big"), public["e"], public["n"])
    try:
        expected = _pkcs1_pad(message, key_bytes)
    except ValueError:
        return False
    return recovered.to_bytes(key_bytes, "big") == expected


# ==========================================================================
# Key / certificate serialization
# ==========================================================================
def _subject_public_key_info(key: Dict[str, int]) -> bytes:
    rsa_public_key = _der_seq(_der_int(key["n"]), _der_int(key["e"]))
    return _der_seq(
        _algorithm_identifier(_OID_RSA_ENCRYPTION),
        _der_bit_string(rsa_public_key),
    )


def _key_identifier(key: Dict[str, int]) -> bytes:
    """RFC 5280 method-1 key identifier: SHA-1 of the RSA public key bytes."""
    rsa_public_key = _der_seq(_der_int(key["n"]), _der_int(key["e"]))
    return hashlib.sha1(rsa_public_key).digest()  # nosec B324 - SKI per RFC 5280


def _pem(der: bytes, label: str) -> str:
    body = base64.encodebytes(der).decode("ascii")
    return "-----BEGIN {0}-----\n{1}-----END {0}-----\n".format(label, body)


def private_key_pem(key: Dict[str, int]) -> str:
    """Serialize *key* as an unencrypted PKCS#8 ``PRIVATE KEY`` PEM."""
    exponent1 = key["d"] % (key["p"] - 1)
    exponent2 = key["d"] % (key["q"] - 1)
    coefficient = _modinv(key["q"], key["p"])
    rsa_private_key = _der_seq(
        _der_int(0),
        _der_int(key["n"]),
        _der_int(key["e"]),
        _der_int(key["d"]),
        _der_int(key["p"]),
        _der_int(key["q"]),
        _der_int(exponent1),
        _der_int(exponent2),
        _der_int(coefficient),
    )
    private_key_info = _der_seq(
        _der_int(0),
        _algorithm_identifier(_OID_RSA_ENCRYPTION),
        _der_octet_string(rsa_private_key),
    )
    return _pem(private_key_info, "PRIVATE KEY")


def certificate_pem(cert_der: bytes) -> str:
    """Serialize a certificate DER blob as a ``CERTIFICATE`` PEM."""
    return _pem(cert_der, "CERTIFICATE")


def pem_to_der(text: str) -> bytes:
    """Decode the base64 body of a single PEM block to DER bytes."""
    body = "".join(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("-----")
    )
    return base64.b64decode(body)


def load_private_key_pem(text: str) -> Dict[str, int]:
    """Parse an unencrypted PKCS#8 ``PRIVATE KEY`` PEM into key components.

    Only the RSA key material this module writes is supported; the algorithm
    identifier is assumed to be ``rsaEncryption``.

    :returns: A dict with ``n, e, d, p, q``.
    :rtype: dict
    """
    der = pem_to_der(text)
    # PrivateKeyInfo ::= SEQUENCE { version, algorithm, privateKey OCTET STRING }
    _, info_start, _ = _read_tlv(der, 0)
    offset = info_start
    _, _, offset = _read_tlv(der, offset)  # skip version
    _, _, offset = _read_tlv(der, offset)  # skip algorithm identifier
    _, key_start, key_end = _read_tlv(der, offset)  # privateKey OCTET STRING
    rsa_der = der[key_start:key_end]
    # RSAPrivateKey ::= SEQUENCE { version, n, e, d, p, q, ... }
    _, seq_start, _ = _read_tlv(rsa_der, 0)
    pointer = seq_start
    values = []
    for _ in range(6):
        _, value_start, value_end = _read_tlv(rsa_der, pointer)
        values.append(int.from_bytes(rsa_der[value_start:value_end], "big"))
        pointer = value_end
    return {
        "n": values[1],
        "e": values[2],
        "d": values[3],
        "p": values[4],
        "q": values[5],
    }


# ==========================================================================
# Certificate extensions
# ==========================================================================
def _extension(oid: str, critical: bool, value_der: bytes) -> bytes:
    items = [_der_oid(oid)]
    if critical:
        items.append(_der_bool(True))
    items.append(_der_octet_string(value_der))
    return _der_seq(*items)


def _key_usage_value(bit_positions: List[int]) -> bytes:
    highest = max(bit_positions)
    data = bytearray(highest // 8 + 1)
    for position in bit_positions:
        data[position // 8] |= 0x80 >> (position % 8)
    unused_bits = 7 - (highest % 8)
    return _der_bit_string(bytes(data), unused_bits)


def _san_value(dns_names: List[str], ip_addresses: List[bytes]) -> bytes:
    general_names = b""
    for name in dns_names:
        general_names += _der_implicit(2, name.encode("ascii"))  # dNSName
    for packed_ip in ip_addresses:
        general_names += _der_implicit(7, packed_ip)  # iPAddress
    return _der_seq(general_names)


# ==========================================================================
# Certificate assembly
# ==========================================================================
def _validity(days: int) -> Tuple[bytes, bytes]:
    # Backdate notBefore slightly to tolerate minor clock skew between the
    # server and clients, while keeping the total span exactly *days* so the
    # leaf stays under Chrome's 398-day cap.
    now = datetime.datetime.now(datetime.timezone.utc)
    not_before = now - datetime.timedelta(hours=1)
    not_after = not_before + datetime.timedelta(days=days)
    return _encode_time(not_before), _encode_time(not_after)


def _serial_number() -> int:
    # A positive, ~64-bit random serial; uniqueness across renewals is all that
    # matters for a single-CA local deployment.
    return secrets.randbits(64) | 1


def _tbs_certificate(
    serial: int,
    issuer: bytes,
    subject: bytes,
    subject_key: Dict[str, int],
    extensions: List[bytes],
    days: int,
) -> bytes:
    not_before, not_after = _validity(days)
    return _der_seq(
        _der_explicit(0, _der_int(2)),  # version v3
        _der_int(serial),
        _algorithm_identifier(_OID_SHA256_WITH_RSA),
        issuer,
        _der_seq(not_before, not_after),
        subject,
        _subject_public_key_info(subject_key),
        _der_explicit(3, _der_seq(*extensions)),
    )


def _assemble(tbs_certificate: bytes, signing_key: Dict[str, int]) -> bytes:
    signature = sign(signing_key, tbs_certificate)
    return _der_seq(
        tbs_certificate,
        _algorithm_identifier(_OID_SHA256_WITH_RSA),
        _der_bit_string(signature),
    )


def build_ca_cert(key: Dict[str, int], common_name: str, days: int) -> bytes:
    """Build a self-signed CA certificate DER, signed by its own *key*."""
    name = _name(common_name)
    extensions = [
        _extension(_OID_BASIC_CONSTRAINTS, True, _der_seq(_der_bool(True))),
        _extension(
            _OID_KEY_USAGE,
            True,
            _key_usage_value([_KU_KEY_CERT_SIGN, _KU_CRL_SIGN]),
        ),
        _extension(_OID_SUBJECT_KEY_ID, False, _der_octet_string(_key_identifier(key))),
    ]
    tbs = _tbs_certificate(_serial_number(), name, name, key, extensions, days)
    return _assemble(tbs, key)


def build_leaf_cert(
    leaf_key: Dict[str, int],
    ca_key: Dict[str, int],
    leaf_common_name: str,
    ca_common_name: str,
    dns_names: List[str],
    ip_addresses: List[bytes],
    days: int,
) -> bytes:
    """Build a server (leaf) certificate DER signed by the CA's *ca_key*."""
    extensions = [
        # cA defaults to FALSE, so an empty SEQUENCE is the DER for CA:FALSE.
        _extension(_OID_BASIC_CONSTRAINTS, True, _der_seq()),
        _extension(
            _OID_KEY_USAGE,
            True,
            _key_usage_value([_KU_DIGITAL_SIGNATURE, _KU_KEY_ENCIPHERMENT]),
        ),
        _extension(_OID_EXT_KEY_USAGE, False, _der_seq(_der_oid(_OID_SERVER_AUTH))),
        _extension(_OID_SUBJECT_ALT_NAME, False, _san_value(dns_names, ip_addresses)),
        _extension(
            _OID_SUBJECT_KEY_ID,
            False,
            _der_octet_string(_key_identifier(leaf_key)),
        ),
        _extension(
            _OID_AUTHORITY_KEY_ID,
            False,
            _der_seq(_der_implicit(0, _key_identifier(ca_key))),
        ),
    ]
    tbs = _tbs_certificate(
        _serial_number(),
        _name(ca_common_name),
        _name(leaf_common_name),
        leaf_key,
        extensions,
        days,
    )
    return _assemble(tbs, ca_key)


# ==========================================================================
# Minimal DER reading (renewal checks only)
# ==========================================================================
def _read_tlv(data: bytes, offset: int) -> Tuple[int, int, int]:
    """Read one DER element, returning ``(tag, content_start, content_end)``."""
    tag = data[offset]
    index = offset + 1
    length_byte = data[index]
    index += 1
    if length_byte & 0x80:
        num_octets = length_byte & 0x7F
        length = int.from_bytes(data[index : index + num_octets], "big")
        index += num_octets
    else:
        length = length_byte
    return tag, index, index + length


def _split_certificate(cert_der: bytes) -> Tuple[bytes, bytes]:
    """Return the raw ``tbsCertificate`` bytes and the signature bytes."""
    _, body_start, _ = _read_tlv(cert_der, 0)  # outer Certificate SEQUENCE
    _, _, tbs_end = _read_tlv(cert_der, body_start)
    tbs_der = cert_der[body_start:tbs_end]
    _, _, alg_end = _read_tlv(cert_der, tbs_end)  # signatureAlgorithm
    _, sig_start, sig_end = _read_tlv(cert_der, alg_end)  # signature BIT STRING
    signature = cert_der[sig_start + 1 : sig_end]  # drop the unused-bits octet
    return tbs_der, signature


def _decode_time(tag: int, raw: bytes) -> datetime.datetime:
    text = raw.decode("ascii")
    if tag == 0x17:  # UTCTime: YYMMDDHHMMSSZ
        two_digit_year = int(text[0:2])
        year = 2000 + two_digit_year if two_digit_year < 50 else 1900 + two_digit_year
        text = text[2:]
    else:  # GeneralizedTime: YYYYMMDDHHMMSSZ
        year = int(text[0:4])
        text = text[4:]
    return datetime.datetime(
        year,
        int(text[0:2]),
        int(text[2:4]),
        int(text[4:6]),
        int(text[6:8]),
        int(text[8:10]),
        tzinfo=datetime.timezone.utc,
    )


def certificate_not_after(cert_der: bytes) -> datetime.datetime:
    """Return the ``notAfter`` timestamp of a certificate as an aware UTC datetime."""
    tbs_der, _ = _split_certificate(cert_der)
    _, content_start, _ = _read_tlv(tbs_der, 0)  # tbsCertificate SEQUENCE
    offset = content_start
    tag, _, end = _read_tlv(tbs_der, offset)
    if tag == 0xA0:  # optional explicit version [0]
        offset = end
    for _ in range(3):  # skip serialNumber, signature, issuer
        _, _, offset = _read_tlv(tbs_der, offset)
    _, validity_start, _ = _read_tlv(tbs_der, offset)  # validity SEQUENCE
    _, _, not_before_end = _read_tlv(tbs_der, validity_start)
    tag, na_start, na_end = _read_tlv(tbs_der, not_before_end)
    return _decode_time(tag, tbs_der[na_start:na_end])


def certificate_signed_by(cert_der: bytes, ca_key: Dict[str, int]) -> bool:
    """Return True if *cert_der* carries a valid signature from *ca_key*."""
    try:
        tbs_der, signature = _split_certificate(cert_der)
    except (IndexError, ValueError):
        return False
    return _verify(_public_key(ca_key), tbs_der, signature)
