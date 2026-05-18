"""
minimost.__main__
=================

Command-line entry point for the MiniMost development server.

This module is invoked either through the ``minimost`` console script
installed by ``pip``, or directly with ``python -m minimost``.  It parses
command-line arguments and starts the Flask built-in WSGI server.

.. note::

   The built-in server is intended for **development and small private
   networks** only.  For production use, run MiniMost behind Gunicorn or
   another WSGI server — see :doc:`/deployment`.

Usage::

    # Default: binds to 127.0.0.1:5000
    minimost

    # Accessible from the local network on port 8080
    minimost --host 0.0.0.0 --port 8080

    # Equivalent without installation
    python -m minimost --host 0.0.0.0 --port 8080
"""

import argparse

from minimost import create_app


def main():
    """Parse arguments and start the MiniMost development server.

    Reads ``--host`` and ``--port`` from the command line, then calls
    :func:`minimost.create_app` to obtain a configured
    :class:`flask.Flask` instance and starts it with
    :meth:`~flask.Flask.run`.

    Debug mode is explicitly disabled so that the Werkzeug reloader and
    interactive debugger are never active, even when the environment variable
    ``FLASK_ENV=development`` is set.

    Command-line arguments:

    ``--host`` : str, optional
        The IP address or hostname to bind to.  Defaults to ``127.0.0.1``
        (loopback only).  Use ``0.0.0.0`` to accept connections on all
        network interfaces.

    ``--port`` : int, optional
        The TCP port to listen on.  Defaults to ``5000``.

    :raises SystemExit: If unrecognised arguments are passed (delegated to
        :class:`argparse.ArgumentParser`).

    Example::

        # Programmatic call (useful in tests)
        import sys
        sys.argv = ["minimost", "--port", "9000"]
        main()
    """
    parser = argparse.ArgumentParser(description="Run the MiniMost server")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Address to listen on (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="Port to listen on (default: 5000)"
    )
    args = parser.parse_args()

    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
