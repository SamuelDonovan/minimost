"""Guard that the shipped app code (src/minimost) stays Python 3.6 compatible.

``pyproject.toml`` declares ``requires-python = ">=3.6"``, so every module that
ships in the wheel must avoid syntax/stdlib features newer than 3.6. We enforce
that statically with `vermin <https://github.com/netromdk/vermin>`_ rather than
juggling multiple interpreters in CI.

If a module ever needs a runtime-guarded use of a newer feature (e.g. an import
wrapped in ``suppress`` with an older fallback), annotate that line with a
``# novermin`` comment so vermin ignores it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).parent.parent / "src" / "minimost"
_TARGET = "3.6"


def test_src_is_python36_compatible():
    pytest.importorskip("vermin", reason="vermin is required for the 3.6 compat check")

    # vermin ships no ``__main__``, so invoke its entry point directly. ``main()``
    # reads sys.argv, which ``python -c`` populates from the trailing arguments.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from vermin import main; sys.exit(main())",
            "-t={}".format(_TARGET),
            "--violations",  # exit non-zero unless the target is met
            "--no-tips",
            str(_SRC),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Files in src/minimost are not Python {} compatible.\n"
        "Annotate intentional, runtime-guarded uses with a '# novermin' comment.\n\n"
        "{}".format(_TARGET, result.stdout + result.stderr)
    )
