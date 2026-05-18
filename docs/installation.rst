Installation
============

Requirements
------------

- **Python 3.6 or later** — MiniMost uses only standard-library modules plus
  Flask. No C extensions are required.
- **Flask** — the only runtime dependency. It is installed automatically when
  you install MiniMost with ``pip``.
- **SQLite** — bundled with Python; no separate installation needed.

Optional (for production):

- **Gunicorn** — recommended WSGI server for multi-user deployments.
- **Nginx** (or similar) — reverse proxy for TLS termination and static file
  serving.

From Source (Recommended)
--------------------------

Clone the repository and install in editable mode::

    git clone https://github.com/SamuelDonovan/minimost.git
    cd minimost
    pip install -e .

Editable mode (``-e``) means changes to the source files take effect
immediately without reinstalling.

From a Wheel (Air-gapped Environments)
---------------------------------------

If the server has no internet access, download the Flask wheel and its
dependencies on a connected machine::

    pip download flask -d ./wheels

Transfer the ``wheels/`` directory to the server, then install::

    pip install --no-index --find-links=./wheels flask
    pip install --no-index minimost-0.1.0-py3-none-any.whl

Running for the First Time
--------------------------

After installation, start the server::

    minimost

Or without installing::

    python3 -m minimost

The server starts at http://127.0.0.1:5000.

On the first request, MiniMost automatically creates:

- ``secret.key`` — a 64-character hex secret used for session signing.
- ``auth.db`` — the authentication database.
- ``presence.db`` — the shared real-time state database.
- ``users/`` — directory for per-user message databases.
- ``uploads/`` — directory for image attachments.

Open http://127.0.0.1:5000 in a browser, click **Sign up**, and create the
first account.

Verifying the Installation
--------------------------

After starting the server you should see Flask's startup banner::

     * Running on http://127.0.0.1:5000

Navigate to that URL. You should be redirected to the login page. If you see
a Python traceback instead, check:

1. Python version: ``python3 --version`` (must be 3.6+).
2. Flask is installed: ``python3 -c "import flask; print(flask.__version__)"``
3. The current directory has write permissions (needed for database creation).

Development Dependencies
-------------------------

To run the code formatter::

    pip install -e ".[dev]"
    black src/

The ``dev`` extra installs `Black <https://black.readthedocs.io/>`_, which is
also enforced as a pre-commit hook::

    pip install pre-commit
    pre-commit install

Sphinx Documentation Dependencies
-----------------------------------

To build this documentation locally::

    pip install sphinx sphinx-rtd-theme
    cd docs
    make html

The generated HTML will be in ``docs/_build/html/``.

Upgrading
---------

Pull the latest changes and reinstall::

    git pull
    pip install -e .

Because MiniMost uses ``CREATE TABLE IF NOT EXISTS`` for all schema
definitions, database migrations are handled automatically — no migration
scripts are needed for minor updates.
