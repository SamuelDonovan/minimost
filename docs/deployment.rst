Deployment
==========

Ports and Firewall
------------------

MiniMost listens on a small, fixed set of ports. Only the application port and
the STUN port are opened *on the server*; WebRTC call/screen-share media flows
directly between the participating clients and never touches the server.

.. list-table::
   :header-rows: 1
   :widths: 24 8 20 48

   * - Port
     - Protocol
     - Where to open it
     - Purpose
   * - ``6767`` (Gunicorn) / ``5000`` (dev server)
     - TCP
     - Inbound on the **server**
     - The HTTPS web app: page loads, chat polling, file uploads, and all
       call/screen-share **signalling** (offer/answer/ICE). This is the only
       port required for text chat. Change it with the ``--port`` flag (dev
       server) or the ``bind`` line in ``gunicorn.conf.py``.
   * - ``3478``
     - UDP
     - Inbound on the **server**
     - The bundled STUN server, used by WebRTC to discover each peer's real LAN
       IP. Required for voice/video calls and screen sharing. Change it with
       ``stun_port`` in ``settings.json`` (must be ``1``–``65535``; avoid the OS
       ephemeral range).
   * - Ephemeral UDP (Linux default ``32768``–``60999``)
     - UDP
     - **Between clients**, both directions
     - The peer-to-peer WebRTC media path (audio, video, and screen frames). The
       browser picks these ports dynamically per connection; they cannot be
       pinned without a TURN server, which MiniMost does not use. Relevant only
       if clients sit on segmented LANs or run host firewalls.

Key points:

- **Text chat needs only the one TCP application port.** Everything else is for
  calls and screen sharing.
- **No outbound internet access is required.** There is no external database and
  no public STUN/TURN server, so MiniMost runs fully air-gapped.
- **No TURN relay.** Peers must be on the same LAN/subnet and able to reach one
  another over UDP; connections across different subnets or the public internet
  will not establish.
- **SQLite is file-based** — there is no database port to open.
- The dev server defaults to ``127.0.0.1`` (loopback only); pass
  ``--host 0.0.0.0`` to accept LAN connections. Gunicorn binds ``0.0.0.0`` by
  default.

Example — opening the required ports with ``firewalld`` (adjust the application
port to match your deployment)::

    # Application (HTTPS) — Gunicorn default
    sudo firewall-cmd --permanent --add-port=6767/tcp
    # Bundled STUN server
    sudo firewall-cmd --permanent --add-port=3478/udp
    # WebRTC media (ephemeral UDP range) — only if a host firewall is active
    sudo firewall-cmd --permanent --add-port=32768-60999/udp
    sudo firewall-cmd --reload

Or with ``ufw``::

    sudo ufw allow 6767/tcp
    sudo ufw allow 3478/udp
    sudo ufw allow 32768:60999/udp

Administrator Setup Checklist
-----------------------------

A complete first-time setup on a fresh host:

1. **Install Python 3.6+ and MiniMost** (``pip install minimost-*.whl``, or
   ``pip install -e .`` from a source checkout). The only runtime dependency is
   Flask; install ``gunicorn`` separately for production. The self-signed TLS
   certificate is generated in pure Python on first run, so no ``openssl``
   binary (or any other external tool) is required. See `TLS Certificates`_.
2. **Choose a working/data directory the service account can write to.** All
   runtime state — ``auth.db``, ``presence.db``, ``users/``, ``uploads/``,
   ``avatars/``, ``secret.key`` and the generated ``cert.pem`` / ``key.pem`` — is
   written there (the project root in a source checkout, or the process working
   directory under Gunicorn). ``settings.json`` ships inside the package and is
   read from there.
3. **Open the firewall ports** listed in `Ports and Firewall`_ — the TCP
   application port for everyone, plus UDP ``3478`` and the ephemeral UDP range
   if you want calls and screen sharing.
4. **Preserve ``secret.key`` across restarts.** It is generated automatically on
   first run and signs session cookies; deleting it logs every user out.
5. **(Production) Run behind Gunicorn**, optionally as a systemd service, and
   review the ``bind`` address/port in ``gunicorn.conf.py``. See
   `Gunicorn (Recommended for Production)`_ and `Systemd Service`_.
6. **On each client**, browse to ``https://<server-ip>:<port>`` and trust the
   certificate authority once (see `Trusting the Certificate`_).

TLS Certificates
----------------

Voice and video calling requires a **secure context** — browsers will not
grant microphone or camera access over plain HTTP.  MiniMost handles this
automatically by generating its own certificate authority and a server
certificate signed by it:

- On first run, both the development server (``minimost`` / ``python3 -m
  minimost``) and the Gunicorn configuration file (``gunicorn.conf.py``)
  generate, in pure Python (standard library only — no ``openssl`` binary):

  - ``ca.pem`` / ``ca-key.pem`` — a long-lived **local certificate authority**
    (valid for 10 years).  ``ca.pem`` is the file clients import to trust the
    server; ``ca-key.pem`` is its private signing key and must never leave the
    server.
  - ``cert.pem`` / ``key.pem`` — the **server (leaf) certificate** actually
    served to clients, signed by the CA.  It covers ``localhost``, the
    server's short hostname, its FQDN, its Avahi/mDNS ``.local`` name, and its
    local IP via Subject Alternative Names so it is valid for LAN access.

- The leaf is capped at **398 days**, because Chrome rejects any server
  certificate valid for longer (``NET::ERR_CERT_VALIDITY_TOO_LONG``) regardless
  of whether it is trusted.  The leaf is **regenerated automatically** when it
  is missing, no longer chains to the CA, or within 30 days of expiry — so a
  routine restart silently renews it.  Because it is re-signed by the *same*
  CA, clients never need to re-import anything.
- If certificate generation fails for any reason, a warning is printed
  to stderr and the server starts over plain HTTP.  Chat will work normally
  but calling will not.

.. _Trusting the Certificate:

Trusting the certificate
~~~~~~~~~~~~~~~~~~~~~~~~~~

Because the CA is self-generated, browsers do not trust it until you import
``ca.pem`` once per device.  Until you do, the site shows a **"Not secure"**
warning and an installed PWA cannot hide the address bar.

The easiest way to obtain the file is the in-app download link: open the
**Help** menu (``?``) and, under **Trusting This Site**, click **Download
certificate**.  This downloads ``ca.pem`` from the server's ``/ca.pem``
endpoint.  (Only the public CA certificate is served there; the signing key is
never exposed.)

Then import it:

- **Chrome / Edge:** open ``chrome://certificate-manager`` →
  **Local certificates** → **Trusted Certificates** → **Import**, select the
  downloaded file, and restart the browser.
- **Firefox:** Settings → Privacy & Security → Certificates →
  **View Certificates…** → **Authorities** → **Import…**, then tick
  *Trust this CA to identify websites*.
- **System-wide (Linux):** copy ``ca.pem`` to
  ``/usr/local/share/ca-certificates/minimost.crt`` and run
  ``sudo update-ca-certificates``.

You only need to do this once per device.  Subsequent leaf renewals are
trusted automatically because they are signed by the CA you already imported.

Using a public CA instead
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To replace the self-signed setup with a proper CA-signed certificate (e.g.
from Let's Encrypt), place your own ``cert.pem`` and ``key.pem`` (or equivalent
PEM files) in the project root before starting the server.  When a valid leaf
is already present, it is reused as-is; delete ``ca.pem``/``ca-key.pem`` if you
no longer want the local CA on disk.

Networking for Calls and Screen Sharing
----------------------------------------

Call and screen-share **media** flows peer-to-peer over WebRTC; it never
passes through the server.  Only the page, the HTTP signalling
(``/calls/<id>/signal[s]``), and the STUN server involve the server.  For
calls to connect:

- **Peers must be on the same LAN/subnet** and able to reach each other over
  **UDP** (WebRTC opens ephemeral UDP ports for the direct media path).  There
  is no TURN relay, so peers on different subnets or across the public internet
  will not connect.
- **The bundled STUN server must be reachable** on UDP ``3478`` (configurable
  via ``stun_port`` in ``settings.json``).  It is started automatically with
  the app and bound to all interfaces.  It lets each peer discover its real LAN
  IP, which is what avoids the ``*.local`` mDNS resolution that otherwise breaks
  calls on LANs without avahi/Bonjour — so **no external/public STUN/TURN
  server is needed and calls work air-gapped**.
- If a host firewall is enabled, allow inbound UDP on ``3478`` and the
  ephemeral UDP range on the LAN interface — see `Ports and Firewall`_ for the
  full list and ``firewalld`` / ``ufw`` examples.

If a call fails to connect, open the browser console: ``_logPeerState()`` logs
the ICE state and, on failure, whether the STUN/UDP path is the likely cause.

Development Server
------------------

The built-in Flask development server is the fastest way to get started and
is suitable for **personal use or very small teams** (1–5 users) on a trusted
local network::

    minimost

Or without the console script::

    python3 -m minimost

By default this binds to ``127.0.0.1:5000`` (loopback only) over HTTPS.
To allow access from other machines on your network::

    minimost --host 0.0.0.0

To use a non-default port::

    minimost --host 0.0.0.0 --port 8080

Other machines can then reach the server at ``https://<server-ip>:8080``.

.. warning::

   Flask's built-in server is single-threaded and not designed for concurrent
   use. For more than a handful of simultaneous users, use Gunicorn.

Gunicorn (Recommended for Production)
--------------------------------------

`Gunicorn <https://gunicorn.org/>`_ is a production-grade WSGI server that
handles multiple simultaneous requests using multiple worker processes.
MiniMost ships a Gunicorn configuration **both** as a top-level
``gunicorn.conf.py`` (for source checkouts) and as an importable module inside
the wheel (``minimost.gunicorn_conf``), so an installed copy needs no checkout.

Install Gunicorn::

    pip install gunicorn

From a **pip-installed** package, point Gunicorn at the packaged config module
(handles TLS cert generation automatically)::

    gunicorn "minimost:create_app()" -c python:minimost.gunicorn_conf

From a **source checkout**, the top-level config file is equivalent — it simply
puts ``src/`` on the path and re-exports the packaged settings::

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

1. **Use HTTPS** — MiniMost generates a self-signed certificate automatically.
   For a public-facing deployment, replace it with a CA-signed certificate
   (Let's Encrypt is free) by placing ``cert.pem`` and ``key.pem`` in the
   project root before starting the server.  HTTPS is also required for
   voice and video calling.
2. **Run as a non-root user** — create a dedicated ``minimost`` user account.
3. **Restrict filesystem permissions** — the ``minimost`` user should own
   ``auth.db``, ``presence.db``, ``users/``, and ``uploads/``; no other
   users should be able to read them.  Protect ``key.pem`` with the same
   care — it is the TLS private key.
4. **Keep Flask debug mode off** — the :func:`minimost.create_app` factory
   always passes ``debug=False`` to ``app.run()``, but verify the
   ``FLASK_ENV`` variable is not set to ``development``.
5. **Schedule image cleanup** — add a cron entry for ``clean.py`` to
   prevent unbounded disk growth (see :doc:`administration`).
6. **Back up regularly** — back up ``auth.db``, ``presence.db``, and
   ``users/messages.db``.
