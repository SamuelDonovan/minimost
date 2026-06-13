"""Tests for the pure-stdlib PKI toolkit (minimost._pki) and certificate
provisioning policy (minimost.certs).

These exercise the full life-cycle without any external ``openssl`` binary: key
generation, the DER/X.509 builders, signing/verification, the PKCS#8 round-trip,
and the renewal decisions in :func:`minimost.certs.ensure_certs`. The strongest
guarantee is that Python's own ``ssl`` module (OpenSSL under the hood — the same
loader Flask uses) accepts the generated certificate and key.
"""

import datetime
import ssl

import minimost
from minimost import _pki, certs

# A single shared 2048-bit key keeps the suite fast: keygen is the slow part and
# nothing here depends on having a *fresh* key per test.
_KEY = _pki.generate_key()


def test_generated_key_components_are_consistent():
    n, e, d, p, q = (_KEY[k] for k in ("n", "e", "d", "p", "q"))
    assert n.bit_length() == 2048
    assert e == 65537
    assert p * q == n
    # d is the inverse of e modulo the totient.
    assert (e * d) % ((p - 1) * (q - 1)) == 1


def test_sign_verify_round_trip():
    message = b"the quick brown fox"
    signature = _pki.sign(_KEY, message)
    public = {"n": _KEY["n"], "e": _KEY["e"]}
    assert _pki._verify(public, message, signature) is True
    assert _pki._verify(public, b"tampered", signature) is False


def test_private_key_pkcs8_round_trips():
    pem = _pki.private_key_pem(_KEY)
    assert "BEGIN PRIVATE KEY" in pem
    loaded = _pki.load_private_key_pem(pem)
    assert loaded == {k: _KEY[k] for k in ("n", "e", "d", "p", "q")}


def test_der_integer_pads_high_bit():
    # 0x80 would read as negative without a leading zero byte.
    assert _pki._der_int(0x80) == bytes([0x02, 0x02, 0x00, 0x80])
    assert _pki._der_int(0) == bytes([0x02, 0x01, 0x00])


def test_oid_encoding_matches_known_value():
    # rsaEncryption 1.2.840.113549.1.1.1
    expected = bytes([0x06, 0x09, 0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x01, 0x01])
    assert _pki._der_oid("1.2.840.113549.1.1.1") == expected


def test_leaf_chains_to_ca_and_carries_san():
    ca_key = _pki.generate_key()
    ca_der = _pki.build_ca_cert(ca_key, "Test CA", 3650)
    leaf_der = _pki.build_leaf_cert(
        _KEY,
        ca_key,
        "leaf",
        "Test CA",
        ["localhost", "example.local"],
        [b"\x7f\x00\x00\x01"],
        398,
    )
    assert _pki.certificate_signed_by(leaf_der, ca_key) is True
    # A self-signed CA verifies under its own key; a leaf does not verify under
    # an unrelated key.
    assert _pki.certificate_signed_by(ca_der, ca_key) is True
    assert _pki.certificate_signed_by(leaf_der, _KEY) is False


def test_certificate_not_after_is_within_chrome_cap():
    leaf_der = _pki.build_leaf_cert(
        _KEY, _KEY, "leaf", "leaf", ["localhost"], [b"\x7f\x00\x00\x01"], 398
    )
    not_after = _pki.certificate_not_after(leaf_der)
    span = not_after - datetime.datetime.now(datetime.timezone.utc)
    # Chrome rejects server certs valid for more than 398 days.
    assert 0 < span.total_seconds() <= 398 * 24 * 3600


def test_certificate_signed_by_rejects_garbage():
    assert _pki.certificate_signed_by(b"not a certificate", _KEY) is False


def test_ensure_certs_output_loads_in_ssl(tmp_path):
    cert, key = certs.ensure_certs(tmp_path)
    assert cert is not None and key is not None
    assert (tmp_path / "ca.pem").exists()
    # The definitive check: the stdlib TLS loader (OpenSSL) accepts the pair.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))


def test_ensure_certs_is_idempotent(tmp_path):
    cert, _ = certs.ensure_certs(tmp_path)
    assert cert is not None
    first = cert.read_text()
    certs.ensure_certs(tmp_path)
    # A fresh leaf is far from expiry and chains to the CA, so it is not redone.
    assert cert.read_text() == first


def test_ensure_certs_renews_leaf_but_keeps_ca(tmp_path):
    certs.ensure_certs(tmp_path)
    ca_before = (tmp_path / "ca.pem").read_text()
    (tmp_path / "cert.pem").unlink()
    (tmp_path / "key.pem").unlink()

    certs.ensure_certs(tmp_path)
    assert (tmp_path / "ca.pem").read_text() == ca_before
    ca_key = _pki.load_private_key_pem((tmp_path / "ca-key.pem").read_text())
    leaf_der = _pki.pem_to_der((tmp_path / "cert.pem").read_text())
    assert _pki.certificate_signed_by(leaf_der, ca_key) is True


def test_ensure_certs_regenerates_foreign_leaf(tmp_path):
    certs.ensure_certs(tmp_path)
    ca_key = _pki.load_private_key_pem((tmp_path / "ca-key.pem").read_text())
    # Replace the leaf with one signed by an unrelated CA.
    foreign = _pki.generate_key()
    foreign_der = _pki.build_ca_cert(foreign, "Foreign", 3650)
    (tmp_path / "cert.pem").write_text(_pki.certificate_pem(foreign_der))

    assert certs._leaf_needs_renewal(tmp_path / "cert.pem", ca_key) is True
    certs.ensure_certs(tmp_path)
    leaf_der = _pki.pem_to_der((tmp_path / "cert.pem").read_text())
    assert _pki.certificate_signed_by(leaf_der, ca_key) is True


def test_ensure_certs_leaves_user_supplied_cert_untouched(tmp_path):
    # A leaf present without MiniMost's CA is treated as user-supplied.
    (tmp_path / "cert.pem").write_text("USER CERT")
    (tmp_path / "key.pem").write_text("USER KEY")
    cert, _key = certs.ensure_certs(tmp_path)
    assert (tmp_path / "cert.pem").read_text() == "USER CERT"
    assert not (tmp_path / "ca.pem").exists()
    assert cert == tmp_path / "cert.pem"


def test_ensure_certs_handles_generation_failure(tmp_path, monkeypatch):
    # If key generation blows up, provisioning degrades to HTTP rather than
    # crashing the server.
    def boom(*_args, **_kwargs):
        raise RuntimeError("entropy exhausted")

    monkeypatch.setattr(_pki, "generate_key", boom)
    assert certs.ensure_certs(tmp_path) == (None, None)


# --- create_app TLS provisioning (server-agnostic; see minimost._provision_tls)


def test_create_app_provisions_tls_for_any_wsgi_server(monkeypatch):
    # ensure_certs is stubbed so the test does not pay for real RSA keygen; the
    # point is that create_app() calls it and records the paths in config, which
    # is what lets waitress/uWSGI/etc. serve HTTPS without bespoke wiring.
    monkeypatch.delenv("MINIMOST_SKIP_TLS", raising=False)
    monkeypatch.setattr(
        certs, "ensure_certs", lambda directory: ("cert.pem", "key.pem")
    )
    app = minimost.create_app()
    assert app.config["TLS_CERT_FILE"] == "cert.pem"
    assert app.config["TLS_KEY_FILE"] == "key.pem"


def test_create_app_skips_tls_when_disabled(monkeypatch):
    monkeypatch.setenv("MINIMOST_SKIP_TLS", "1")
    app = minimost.create_app()
    assert "TLS_CERT_FILE" not in app.config


def test_create_app_tolerates_tls_generation_failure(monkeypatch):
    # ensure_certs returns (None, None) when generation is skipped/fails; the app
    # must still come up (just without HTTPS).
    monkeypatch.delenv("MINIMOST_SKIP_TLS", raising=False)
    monkeypatch.setattr(certs, "ensure_certs", lambda directory: (None, None))
    app = minimost.create_app()
    assert "TLS_CERT_FILE" not in app.config
