"""Single source of truth for the package version.

This module is read in two places:

* at runtime by :func:`minimost._read_version`, and
* at build time by setuptools, via ``[tool.setuptools.dynamic]`` in
  ``pyproject.toml`` (``version = {attr = "minimost._version.__version__"}``).

Keeping the version in a plain module — rather than relying on
``importlib.metadata`` — means it resolves correctly even on Python 3.6/3.7 and
from an installed wheel, since this file always ships inside the package.
"""

__version__ = "0.0.1"
