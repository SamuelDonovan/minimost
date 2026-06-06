"""
minimost.certs
==============

TLS certificate provisioning for MiniMost.

Voice/video calling requires a **secure context**, so MiniMost serves HTTPS
using a self-managed certificate authority:

- ``ca.pem`` / ``ca-key.pem`` — a long-lived local CA.  ``ca.pem`` is the file
  clients import once to trust the server; ``ca-key.pem`` is its private signing
  key and never leaves the server.
- ``cert.pem`` / ``key.pem`` — the server (leaf) certificate actually presented
  to clients, signed by the CA.  Chrome rejects any server certificate valid for
  more than 398 days (``NET::ERR_CERT_VALIDITY_TOO_LONG``) regardless of trust,
  so the leaf is capped there and regenerated automatically when it is missing,
  no longer chains to the CA, or within 30 days of expiry.  Because renewals are
  re-signed by the *same* CA, clients never need to re-import anything.

This module is the single source of truth for that logic; both the development
server (:mod:`minimost.__main__`) and the Gunicorn configuration
(:mod:`minimost.gunicorn_conf`) call :func:`ensure_certs`.  It depends only on
the standard library and the system ``openssl`` binary.
"""

import os
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

# Validity (days) for the served leaf certificate. Chrome rejects any TLS server
# certificate valid for more than 398 days with NET::ERR_CERT_VALIDITY_TOO_LONG,
# regardless of whether it is trusted.
_LEAF_DAYS = "398"
# The local CA is a trust anchor, not a server cert, so the 398-day cap does not
# apply. Making it long-lived means it only has to be imported into the browser
# once; the leaf it signs renews silently in the background.
_CA_DAYS = "3650"
# Regenerate the leaf when it is within this many seconds of expiry, so a plain
# restart renews it against the already-trusted CA without any browser action.
_LEAF_RENEW_BEFORE = str(30 * 24 * 60 * 60)


def _build_san():
    """Build the subjectAltName string covering every name clients may use."""
    hostname = socket.gethostname()
    fqdn = socket.getfqdn()
    try:
        local_ip = socket.gethostbyname(hostname)
    except socket.gaierror:
        local_ip = None

    # Include the FQDN alongside the short hostname so the certificate matches
    # whichever name clients use to reach the server. A name mismatch keeps the
    # browser on "Not secure", which prevents an installed PWA from hiding the
    # URL bar.
    dns_names = []
    for name in ("localhost", hostname, fqdn):
        if name and name not in dns_names:
            dns_names.append(name)
    # The Avahi/mDNS ".local" name (e.g. "archlinux.local") is how LAN clients
    # usually reach the server, but it is served by mDNS rather than the system
    # FQDN, so socket.getfqdn() never reports it. Add it explicitly.
    if hostname and "." not in hostname:
        mdns_name = f"{hostname}.local"
        if mdns_name not in dns_names:
            dns_names.append(mdns_name)
    san_parts = [f"DNS:{name}" for name in dns_names]
    san_parts.append("IP:127.0.0.1")
    if local_ip and local_ip != "127.0.0.1":
        san_parts.append(f"IP:{local_ip}")
    return ",".join(san_parts)


def _run_openssl(openssl_bin, args):
    return subprocess.run(  # nosec B603
        [openssl_bin, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def _write_tmp_conf(text):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False) as tmp:
        tmp.write(text)
        return tmp.name


def _generate_ca(openssl_bin, ca_cert, ca_key):
    """Create the long-lived local CA that signs the served leaf cert."""
    ca_conf = (
        "[req]\n"
        "distinguished_name = req_dn\n"
        "x509_extensions   = v3_ca\n"
        "prompt            = no\n"
        "\n"
        "[req_dn]\n"
        "CN = MiniMost local CA\n"
        "\n"
        "[v3_ca]\n"
        # CA:TRUE makes this importable into a browser/OS trust store as an
        # authority; keyCertSign lets it sign the leaf served by the app.
        "basicConstraints = critical, CA:TRUE\n"
        "keyUsage = critical, keyCertSign, cRLSign\n"
    )
    conf_path = _write_tmp_conf(ca_conf)
    try:
        return _run_openssl(
            openssl_bin,
            [
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(ca_key),
                "-out",
                str(ca_cert),
                "-days",
                _CA_DAYS,
                "-nodes",
                "-config",
                conf_path,
            ],
        )
    finally:
        os.unlink(conf_path)


def _generate_leaf(openssl_bin, cert_path, key_path, ca_cert, ca_key):
    """Create a short-lived leaf cert signed by the local CA."""
    leaf_conf = (
        "[req]\n"
        "distinguished_name = req_dn\n"
        "req_extensions    = v3_req\n"
        "prompt            = no\n"
        "\n"
        "[req_dn]\n"
        "CN = minimost\n"
        "\n"
        "[v3_req]\n"
        # A leaf, not a CA. serverAuth + the SAN are what Chrome validates.
        "basicConstraints = critical, CA:FALSE\n"
        "keyUsage = critical, digitalSignature, keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        f"subjectAltName = {_build_san()}\n"
    )
    conf_path = _write_tmp_conf(leaf_conf)
    # openssl writes the CSR here; create the temp name up front so we can clean
    # it up regardless of where generation fails.
    csr_path = _write_tmp_conf("")
    try:
        csr = _run_openssl(
            openssl_bin,
            [
                "req",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key_path),
                "-out",
                csr_path,
                "-nodes",
                "-config",
                conf_path,
            ],
        )
        if csr.returncode != 0:
            return csr
        # The SAN/EKU live in the config, not the CSR, so they must be re-applied
        # via -extfile/-extensions when the CA signs the leaf.
        return _run_openssl(
            openssl_bin,
            [
                "x509",
                "-req",
                "-in",
                csr_path,
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(cert_path),
                "-days",
                _LEAF_DAYS,
                "-extfile",
                conf_path,
                "-extensions",
                "v3_req",
            ],
        )
    finally:
        os.unlink(conf_path)
        os.unlink(csr_path)


def ensure_certs(directory):
    """Ensure a CA-signed TLS leaf cert exists in ``directory``.

    Generates a long-lived local CA (``ca.pem``) once and a short-lived leaf
    (``cert.pem``) signed by it, regenerating the leaf when it is missing,
    foreign, or near expiry.  Diagnostics are printed to stderr; on the first
    CA creation, instructions for importing ``ca.pem`` are printed too.

    :param directory: Directory in which the cert files live / are created.
    :type directory: str or pathlib.Path
    :returns: ``(cert_path, key_path)`` as :class:`pathlib.Path` objects on
        success, or ``(None, None)`` if generation is skipped or fails (in which
        case the caller should continue without TLS).
    :rtype: tuple[Path, Path] | tuple[None, None]
    """
    directory = Path(directory)
    cert_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    ca_cert = directory / "ca.pem"
    ca_key = directory / "ca-key.pem"

    # Respect a user-supplied (or legacy self-signed) cert: if a leaf is present
    # but MiniMost's own CA is not, leave the files untouched. Delete cert.pem /
    # key.pem to opt into the managed local-CA model.
    have_leaf = cert_path.exists() and key_path.exists()
    have_ca = ca_cert.exists() and ca_key.exists()
    if have_leaf and not have_ca:
        return cert_path, key_path

    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        print(
            "WARNING: openssl not found on PATH; cannot generate TLS certificates.\n"
            "WARNING: Calls will not work without HTTPS. Install openssl and restart.",
            file=sys.stderr,
        )
        return None, None

    ca_created = False
    if not have_ca:
        result = _generate_ca(openssl_bin, ca_cert, ca_key)
        if result.returncode != 0:
            print(
                "WARNING: Failed to generate the local CA.\n"
                f"WARNING: {result.stderr.strip()}\n"
                "WARNING: Calls will not work without HTTPS.",
                file=sys.stderr,
            )
            return None, None
        ca_created = True

    need_leaf = ca_created or not have_leaf
    if not need_leaf:
        # Regenerate if the leaf no longer chains to the CA (e.g. left over from
        # the older self-signed setup) or is inside the renewal window.
        verify = _run_openssl(
            openssl_bin, ["verify", "-CAfile", str(ca_cert), str(cert_path)]
        )
        checkend = _run_openssl(
            openssl_bin,
            ["x509", "-checkend", _LEAF_RENEW_BEFORE, "-noout", "-in", str(cert_path)],
        )
        need_leaf = verify.returncode != 0 or checkend.returncode != 0

    if need_leaf:
        result = _generate_leaf(openssl_bin, cert_path, key_path, ca_cert, ca_key)
        if result.returncode != 0:
            print(
                "WARNING: Failed to generate the TLS leaf certificate.\n"
                f"WARNING: {result.stderr.strip()}\n"
                "WARNING: Calls will not work without HTTPS.",
                file=sys.stderr,
            )
            return None, None
        print(f"Generated TLS leaf certificate ({cert_path}, {key_path}).")

    if ca_created:
        print(
            f"\nA local certificate authority was created at {ca_cert}.\n"
            "Import THIS file into your browser's trusted certificates once\n"
            "(Chrome: Manage certificates > Local certificates > Trusted Certificates),\n"
            "or download it in-app from the Help menu > Trusting This Site.\n"
            "The served leaf cert renews automatically and never needs re-importing\n"
            "as long as this CA stays trusted.",
            file=sys.stderr,
        )

    return cert_path, key_path
