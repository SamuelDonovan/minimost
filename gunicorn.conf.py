# gunicorn.conf.py
#
# Thin shim for running MiniMost from a source checkout:
#
#     gunicorn "minimost:create_app()" -c gunicorn.conf.py
#
# All of the actual configuration (and TLS certificate provisioning) lives in
# the packaged module ``minimost.gunicorn_conf`` so it ships inside the wheel.
# Once MiniMost is pip-installed you can skip this file entirely and use:
#
#     gunicorn "minimost:create_app()" -c python:minimost.gunicorn_conf
#
# This shim simply puts ``src/`` on the import path (so the package resolves
# without installation) and re-exports every setting from the packaged module.
import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from minimost.gunicorn_conf import *  # noqa: E402,F401,F403

# Ensure Gunicorn's worker/app import also finds the src/ layout when running
# from a checkout that has not been installed.
pythonpath = "src"
