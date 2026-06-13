"""Static guards that the shipped app code (src/minimost) stays runnable on
Windows.

MiniMost targets Windows as a first-class platform: the development server, the
pure-Python TLS certificate generation, the bundled STUN server, and WebRTC
calling all work there (only Gunicorn — POSIX ``fork``/``fcntl`` — does not, and
it is optional). CI runs on Linux, so these tests reject the most common
Windows-breaking constructs *statically*, before they can ship:

* importing a POSIX-only stdlib module (would crash the app at startup),
* calling a POSIX-only ``os`` function (``AttributeError`` on Windows),
* using a POSIX-only ``socket`` constant without a ``hasattr`` guard,
* hardcoding an absolute POSIX path.

This cannot *prove* full compatibility — only a Windows CI runner can do that
(see the note in ``docs/deployment.rst``) — but it catches the classes of
regression that would otherwise silently break the Windows experience.
"""

import ast
from pathlib import Path

_SRC = Path(__file__).parent.parent / "src" / "minimost"

# stdlib modules that exist only on POSIX; importing any of these makes the whole
# application fail to import on Windows.
_UNIX_ONLY_MODULES = {
    "fcntl",
    "grp",
    "pwd",
    "spwd",
    "crypt",
    "termios",
    "tty",
    "pty",
    "posix",
    "resource",
    "syslog",
    "nis",
}

# os.* functions absent on Windows (AttributeError when called). Deliberately
# excludes cross-platform members like chmod/getppid/urandom/kill.
_UNIX_ONLY_OS_ATTRS = {
    "fork",
    "forkpty",
    "getuid",
    "geteuid",
    "getgid",
    "getegid",
    "setuid",
    "seteuid",
    "setgid",
    "setegid",
    "getgroups",
    "setgroups",
    "setpgrp",
    "setpgid",
    "getpgid",
    "getpgrp",
    "setsid",
    "getsid",
    "chown",
    "chroot",
    "mkfifo",
    "mknod",
    "wait3",
    "wait4",
    "getloadavg",
    "sysconf",
}

# socket constants that are POSIX-only. SO_REUSEPORT is legitimately used by the
# STUN server but must stay behind a hasattr() guard; AF_UNIX is forbidden.
_GUARDED_SOCKET_ATTRS = {"SO_REUSEPORT"}
_FORBIDDEN_SOCKET_ATTRS = {"AF_UNIX"}

# String literals starting with one of these are almost certainly hardcoded
# POSIX filesystem paths (Flask route strings like "/login" never match).
_POSIX_PATH_PREFIXES = (
    "/tmp",
    "/var/",
    "/etc/",
    "/dev/",
    "/proc/",
    "/usr/",
    "/opt/",
    "/root/",
    "/run/",
)


def _python_files():
    return sorted(_SRC.rglob("*.py"))


def _docstring_nodes(tree):
    """Return the set of ``id()``s of string-constant nodes that are docstrings.

    Docstrings routinely mention example paths in prose, so the path-literal
    check skips them to avoid false positives.
    """
    ids = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _scan_file(path):
    """Return a list of human-readable Windows-compatibility violations."""
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    try:
        rel = path.relative_to(_SRC.parent.parent)
    except ValueError:
        rel = path.name  # synthetic file outside the repo (self-test)
    docstrings = _docstring_nodes(tree)
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _UNIX_ONLY_MODULES:
                    violations.append(
                        "{}: imports POSIX-only module '{}'".format(rel, top)
                    )
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _UNIX_ONLY_MODULES:
                violations.append("{}: imports POSIX-only module '{}'".format(rel, top))
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base, attr = node.value.id, node.attr
            if base == "os" and attr in _UNIX_ONLY_OS_ATTRS:
                violations.append("{}: uses POSIX-only os.{}".format(rel, attr))
            elif base == "socket" and attr in _FORBIDDEN_SOCKET_ATTRS:
                violations.append("{}: uses POSIX-only socket.{}".format(rel, attr))
            elif base == "socket" and attr in _GUARDED_SOCKET_ATTRS:
                guard = 'hasattr(socket, "{}")'.format(attr)
                if guard not in source and guard.replace('"', "'") not in source:
                    violations.append(
                        "{}: uses socket.{} without a hasattr() guard".format(rel, attr)
                    )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if node.value.startswith(_POSIX_PATH_PREFIXES):
                violations.append(
                    "{}: hardcoded POSIX path literal {!r}".format(rel, node.value)
                )

    return violations


def test_no_windows_incompatible_constructs():
    violations = []
    for path in _python_files():
        violations.extend(_scan_file(path))
    assert (
        not violations
    ), "Windows-incompatible constructs found in src/minimost:\n" + (
        "\n".join("  " + v for v in violations)
    )


def test_scanner_detects_known_bad_patterns(tmp_path):
    """Guard the guard: confirm the scanner actually flags each bad construct."""
    bad = tmp_path / "src" / "minimost" / "bad.py"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "import fcntl\n"
        "import os, socket\n"
        "os.fork()\n"
        "socket.socket(socket.AF_UNIX)\n"
        "socket.setsockopt(socket.SO_REUSEPORT, 1)\n"
        "PATH = '/var/log/minimost.log'\n"
    )
    findings = _scan_file(bad)
    joined = "\n".join(findings)
    assert "POSIX-only module 'fcntl'" in joined
    assert "os.fork" in joined
    assert "socket.AF_UNIX" in joined
    assert "SO_REUSEPORT without a hasattr() guard" in joined
    assert "hardcoded POSIX path" in joined
