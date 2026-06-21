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

This module is the single source of truth for that logic.  :func:`ensure_certs`
is called from :func:`minimost.create_app` (so *any* WSGI server — the dev
server, Gunicorn, waitress, uWSGI, … — provisions certificates with no
server-specific glue), and additionally from the bundled Gunicorn configuration
(:mod:`minimost.gunicorn_conf`), which needs the paths at config-load time to
set its TLS listener.  Both call sites are idempotent.  All certificate
generation is done in pure Python via :mod:`minimost._pki`, so it depends only
on the standard library — there is no longer any dependency on a system
``openssl`` binary (which let provisioning work on Windows too).
"""

import datetime
import os
import secrets
import socket
import stat
import sys
from pathlib import Path

from . import _pki
from .paths import data_dir

# Certificates live in the same data root as the rest of MiniMost's state
# (``secret.key``, the ``users/`` databases) rather than the process working
# directory — see :func:`minimost.paths.data_dir`. On a packaged install this is
# ``/var/lib/minimost``; from a git checkout it is the source root.
#
# Anchoring the certs to a fixed location is deliberate: a client that has
# already imported ``ca.pem`` keeps validating the served leaf no matter which
# directory the server is later launched from.  When the certs lived in
# ``Path.cwd()``, launching from a different directory minted a *second* CA;
# because every CA shared one subject name, browsers matched the stale trusted
# CA to the new leaf and reported the confusing ``SEC_ERROR_BAD_SIGNATURE``
# instead of a clean untrusted-issuer error.
_DATA_DIR = data_dir()

# Validity (days) for the served leaf certificate. Chrome rejects any TLS server
# certificate valid for more than 398 days with NET::ERR_CERT_VALIDITY_TOO_LONG,
# regardless of whether it is trusted.
_LEAF_DAYS = 398
# The local CA is a trust anchor, not a server cert, so the 398-day cap does not
# apply. Making it long-lived means it only has to be imported into the browser
# once; the leaf it signs renews silently in the background.
_CA_DAYS = 3650
# Regenerate the leaf when it is within this many days of expiry, so a plain
# restart renews it against the already-trusted CA without any browser action.
_LEAF_RENEW_DAYS = 30

_CA_COMMON_NAME = "MiniMost local CA"
_LEAF_COMMON_NAME = "minimost"


def default_cert_dir():
    """Return the canonical directory that holds the CA and leaf certificates.

    This is the project/data root, *not* the process working directory — see the
    note on :data:`_DATA_DIR`.

    :rtype: pathlib.Path
    """
    return _DATA_DIR


def _ca_common_name():
    """Build a CA subject name unique to this host and instance.

    Every CA used to share the literal subject ``"MiniMost local CA"``.  When a
    second CA was generated (the server launched from another directory, or a
    fresh checkout), a browser that already trusted the first CA matched it to
    the new leaf *by subject name* and rejected the signature
    (``SEC_ERROR_BAD_SIGNATURE``).  Giving each CA a distinct subject makes a
    stale trust anchor surface as a clean untrusted-issuer error instead, and
    lets several instances be trusted at once.
    """
    try:
        host = socket.gethostname() or "host"
    except OSError:  # pragma: no cover - gethostname failure is rare
        host = "host"
    return "{0} ({1} {2})".format(_CA_COMMON_NAME, host, secrets.token_hex(4))


def _build_san():
    """Build the subjectAltName covering every name clients may use.

    :returns: ``(dns_names, ip_addresses)`` where ``dns_names`` is a list of
        hostname strings and ``ip_addresses`` is a list of packed 4-byte IPv4
        addresses (as produced by :func:`socket.inet_aton`).
    :rtype: tuple[list[str], list[bytes]]
    """
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
        mdns_name = "{0}.local".format(hostname)
        if mdns_name not in dns_names:
            dns_names.append(mdns_name)

    ip_addresses = [socket.inet_aton("127.0.0.1")]
    if local_ip and local_ip != "127.0.0.1":
        try:
            ip_addresses.append(socket.inet_aton(local_ip))
        except OSError:
            pass
    return dns_names, ip_addresses


def _write_private_key(path, pem_text):
    """Write a private-key PEM, restricting it to the owner where supported."""
    path.write_text(pem_text)
    # Best-effort hardening; a no-op on filesystems/platforms without POSIX
    # permission bits (e.g. Windows), which is fine for a LAN-local key.
    try:
        os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _generate_ca(ca_cert, ca_key):
    """Create the long-lived local CA that signs the served leaf cert.

    :returns: The parsed CA private key dict.
    :rtype: dict
    """
    key = _pki.generate_key()
    cert_der = _pki.build_ca_cert(key, _ca_common_name(), _CA_DAYS)
    ca_cert.write_text(_pki.certificate_pem(cert_der))
    _write_private_key(ca_key, _pki.private_key_pem(key))
    return key


def _generate_leaf(cert_path, key_path, ca_cert, ca_key):
    """Create a short-lived leaf cert signed by the local CA.

    The leaf's AuthorityKeyIdentifier is copied from the CA certificate's own
    SubjectKeyIdentifier so the two always match (OpenSSL/browsers reject the
    chain otherwise), even if the CA on disk used an older key-identifier scheme.
    The leaf's issuer name is likewise read from the CA certificate's actual
    subject CN (rather than a constant) so it matches byte-for-byte regardless of
    whether the CA carries a per-instance name or the legacy fixed one.
    """
    dns_names, ip_addresses = _build_san()
    ca_der = _pki.pem_to_der(ca_cert.read_text())
    ca_key_id = _pki.certificate_subject_key_id(ca_der)
    if ca_key_id is None:
        ca_key_id = _pki.key_identifier(ca_key)
    ca_name = _pki.certificate_subject_common_name(ca_der) or _CA_COMMON_NAME
    leaf_key = _pki.generate_key()
    cert_der = _pki.build_leaf_cert(
        leaf_key,
        ca_key,
        ca_key_id,
        _LEAF_COMMON_NAME,
        ca_name,
        dns_names,
        ip_addresses,
        _LEAF_DAYS,
    )
    cert_path.write_text(_pki.certificate_pem(cert_der))
    _write_private_key(key_path, _pki.private_key_pem(leaf_key))


def _leaf_needs_renewal(cert_path, ca_key):
    """Return True if the existing leaf is foreign to the CA or near expiry."""
    try:
        cert_der = _pki.pem_to_der(cert_path.read_text())
        if not _pki.certificate_signed_by(cert_der, ca_key):
            return True
        not_after = _pki.certificate_not_after(cert_der)
    except Exception:  # nosec B110 - any parse failure means "regenerate"
        return True
    renew_threshold = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=_LEAF_RENEW_DAYS
    )
    return not_after <= renew_threshold


def ensure_certs(directory=None):
    """Ensure a CA-signed TLS leaf cert exists in ``directory``.

    Generates a long-lived local CA (``ca.pem``) once and a short-lived leaf
    (``cert.pem``) signed by it, regenerating the leaf when it is missing,
    foreign, or near expiry.  Diagnostics are printed to stderr; on the first
    CA creation, instructions for importing ``ca.pem`` are printed too.

    :param directory: Directory in which the cert files live / are created.
        Defaults to :func:`default_cert_dir` (the fixed data root) when omitted.
    :type directory: str or pathlib.Path or None
    :returns: ``(cert_path, key_path)`` as :class:`pathlib.Path` objects on
        success, or ``(None, None)`` if generation is skipped or fails (in which
        case the caller should continue without TLS).
    :rtype: tuple[Path, Path] | tuple[None, None]
    """
    directory = default_cert_dir() if directory is None else Path(directory)
    cert_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    ca_cert = directory / "ca.pem"
    ca_key_path = directory / "ca-key.pem"

    # Respect a user-supplied (or legacy self-signed) cert: if a leaf is present
    # but MiniMost's own CA is not, leave the files untouched. Delete cert.pem /
    # key.pem to opt into the managed local-CA model.
    have_leaf = cert_path.exists() and key_path.exists()
    have_ca = ca_cert.exists() and ca_key_path.exists()
    if have_leaf and not have_ca:
        return cert_path, key_path

    try:
        ca_created = False
        if have_ca:
            ca_key = _pki.load_private_key_pem(ca_key_path.read_text())
        else:
            ca_key = _generate_ca(ca_cert, ca_key_path)
            ca_created = True

        # Regenerate the leaf if the CA was just created, the leaf is missing,
        # no longer chains to the CA (e.g. left over from the older self-signed
        # setup), or is inside the renewal window.
        if ca_created or not have_leaf or _leaf_needs_renewal(cert_path, ca_key):
            _generate_leaf(cert_path, key_path, ca_cert, ca_key)
            print(
                "Generated TLS leaf certificate ({0}, {1}).".format(
                    cert_path, key_path
                ),
                file=sys.stderr,
            )
    except Exception as exc:  # nosec B110 - degrade to HTTP rather than crash
        print(
            "WARNING: Failed to generate TLS certificates.\n"
            "WARNING: {0}\n"
            "WARNING: Calls will not work without HTTPS.".format(exc),
            file=sys.stderr,
        )
        return None, None

    if ca_created:
        print(
            "\nA local certificate authority was created at {0}.\n"
            "Import THIS file into your browser's trusted certificates once\n"
            "(Chrome: Manage certificates > Local certificates > Trusted Certificates),\n"
            "or download it in-app from the Help menu > Trusting This Site.\n"
            "The served leaf cert renews automatically and never needs re-importing\n"
            "as long as this CA stays trusted.".format(ca_cert),
            file=sys.stderr,
        )

    return cert_path, key_path
