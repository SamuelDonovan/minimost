Deployment
==========

Development Server
------------------

The built-in Flask development server is the fastest way to get started and
is suitable for **personal use or very small teams** (1–5 users) on a trusted
local network::

    minimost

Or without the console script::

    python3 -m minimost

By default this binds to ``127.0.0.1:5000`` (loopback only). To allow access
from other machines on your network::

    minimost --host 0.0.0.0

To use a non-default port::

    minimost --host 0.0.0.0 --port 8080

Other machines can then reach the server at ``http://<server-ip>:8080``.

.. warning::

   Flask's built-in server is single-threaded and not designed for concurrent
   use. For more than a handful of simultaneous users, use Gunicorn.

Gunicorn (Recommended for Production)
--------------------------------------

`Gunicorn <https://gunicorn.org/>`_ is a production-grade WSGI server that
handles multiple simultaneous requests using multiple worker processes.
MiniMost ships with a ``gunicorn.conf.py`` configuration file.

Install Gunicorn::

    pip install gunicorn

Start with the bundled configuration::

    gunicorn "minimost:create_app()" --config gunicorn.conf.py

Or specify options directly::

    gunicorn "minimost:create_app()" \
        --workers 4 \
        --bind 0.0.0.0:6767 \
        --access-logfile - \
        --error-logfile -

.. note::

   Gunicorn workers are created by forking the master process. Because each
   worker has its own SQLite connection(s), WAL journal mode (enabled on all
   databases) is essential for preventing write contention between workers.

Systemd Service
---------------

Running MiniMost as a systemd service ensures it starts automatically on
boot and is restarted if it crashes.

Create a service unit file at ``/etc/systemd/system/minimost.service``:

.. code-block:: ini

    [Unit]
    Description=MiniMost Chat Server
    After=network.target

    [Service]
    Type=notify
    User=minimost
    Group=minimost
    WorkingDirectory=/srv/minimost
    ExecStart=/usr/local/bin/gunicorn \
        "minimost:create_app()" \
        --config /srv/minimost/gunicorn.conf.py
    Restart=on-failure
    RestartSec=5s

    # Security hardening (optional)
    NoNewPrivileges=true
    PrivateTmp=true
    ProtectSystem=strict
    ReadWritePaths=/srv/minimost

    [Install]
    WantedBy=multi-user.target

Enable and start the service::

    sudo systemctl daemon-reload
    sudo systemctl enable minimost
    sudo systemctl start minimost

Check the logs::

    sudo journalctl -u minimost -f

Nginx Reverse Proxy
-------------------

Placing Nginx in front of Gunicorn provides TLS termination, static file
caching, and better connection handling.

**Gunicorn configuration** — use a Unix socket instead of a TCP port:

.. code-block:: python

    # gunicorn.conf.py
    bind = "unix:/run/gunicorn/minimost.sock"

Create the socket directory::

    sudo mkdir -p /run/gunicorn
    sudo chown minimost:minimost /run/gunicorn

**Nginx site configuration**
(``/etc/nginx/sites-available/minimost``):

.. code-block:: nginx

    server {
        listen 80;
        server_name chat.example.com;

        # Redirect HTTP to HTTPS
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name chat.example.com;

        ssl_certificate     /etc/letsencrypt/live/chat.example.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/chat.example.com/privkey.pem;

        # Increase upload limit to match Flask's MAX_CONTENT_LENGTH (16 MiB)
        client_max_body_size 16M;

        # Serve uploaded images directly (bypasses Gunicorn for static files)
        location /files/ {
            alias /srv/minimost/uploads/;
            expires 30d;
            add_header Cache-Control "public, immutable";
        }

        # Proxy all other requests to Gunicorn
        location / {
            proxy_pass http://unix:/run/gunicorn/minimost.sock;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Increase timeouts for link preview requests
            proxy_read_timeout 60s;
        }
    }

Enable the site::

    sudo ln -s /etc/nginx/sites-available/minimost /etc/nginx/sites-enabled/
    sudo nginx -t && sudo systemctl reload nginx

Docker
------

MiniMost does not ship a Dockerfile, but containerising it is straightforward.
A minimal ``Dockerfile``:

.. code-block:: dockerfile

    FROM python:3.11-slim

    WORKDIR /app
    COPY . .
    RUN pip install --no-cache-dir -e . gunicorn

    # Persist databases and uploads across container restarts
    VOLUME ["/app/users", "/app/uploads"]

    EXPOSE 6767

    CMD ["gunicorn", "minimost:create_app()", "--config", "gunicorn.conf.py"]

Build and run::

    docker build -t minimost .
    docker run -d \
        -p 6767:6767 \
        -v minimost_users:/app/users \
        -v minimost_uploads:/app/uploads \
        -v minimost_dbs:/app \
        --name minimost \
        minimost

.. important::

   Mount ``auth.db``, ``presence.db``, and ``secret.key`` from the host or
   a named volume — do **not** bake them into the image.

Security Checklist for Production
----------------------------------

Before exposing MiniMost to a network:

1. **Use HTTPS** — run behind Nginx with a TLS certificate (Let's Encrypt
   is free).
2. **Run as a non-root user** — create a dedicated ``minimost`` user account.
3. **Restrict filesystem permissions** — the ``minimost`` user should own
   ``auth.db``, ``presence.db``, ``users/``, and ``uploads/``; no other
   users should be able to read them.
4. **Keep Flask debug mode off** — the :func:`minimost.create_app` factory
   always passes ``debug=False`` to ``app.run()``, but verify the
   ``FLASK_ENV`` variable is not set to ``development``.
5. **Schedule image cleanup** — add a cron entry for ``clean.py`` to
   prevent unbounded disk growth (see :doc:`administration`).
6. **Back up regularly** — back up ``auth.db``, ``presence.db``, and
   ``users/*.db``.
