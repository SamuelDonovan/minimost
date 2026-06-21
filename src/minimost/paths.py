"""
minimost.paths
==============

Single source of truth for MiniMost's **writable data root**.

Every piece of mutable server state — the ``auth.db``/``presence.db`` SQLite
files, the per-user ``users/`` databases, uploaded files and avatars, the
generated TLS material (``ca.pem``/``cert.pem``/``key.pem``) and the Flask
``secret.key`` — lives under one directory.  This module resolves that
directory in one place so the rest of the package never has to recompute it.

Resolution order
----------------
1. ``$MINIMOST_DATA_DIR`` if set — this is how a packaged install points the
   server at an FHS location such as ``/var/lib/minimost`` (the bundled systemd
   unit sets it via ``StateDirectory=``).  The directory is created (with
   parents) the first time it is resolved, so a fresh install or a manual
   override needs no separate ``mkdir`` step.
2. Otherwise the **source-checkout root** (``src/minimost/../..``).  This keeps
   the historical, zero-config behaviour when running straight from a git
   clone: databases, uploads, certs and ``secret.key`` all sit next to the
   source tree, exactly where the test suite and existing deployments expect
   them.

Because the value is derived from this one function, code that needs an FHS
layout only has to set the environment variable; nothing else changes.
"""

import os
from pathlib import Path

# src/minimost/paths.py -> parents[2] is the checkout root (the directory that
# holds src/, tests/, pyproject.toml). Resolves identically from an installed
# wheel, where it points at site-packages and is therefore *not* writable — which
# is exactly why a packaged install must set $MINIMOST_DATA_DIR instead.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """Return the absolute path of the writable data root.

    See the module docstring for the resolution order.  When
    ``$MINIMOST_DATA_DIR`` is set the directory is created (parents included)
    if it does not yet exist, so callers can rely on it being present.

    :returns: Absolute path to the data root.
    :rtype: pathlib.Path
    """
    env = os.environ.get("MINIMOST_DATA_DIR")
    if env:
        path = Path(env).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()
    return _CHECKOUT_ROOT
