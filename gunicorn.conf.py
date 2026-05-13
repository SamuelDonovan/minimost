# gunicorn.conf.py
import multiprocessing

# --------------------------------------------------------------------
# Server socket
# --------------------------------------------------------------------
bind = "0.0.0.0:6767"
# If behind nginx, use a unix socket instead:
# bind = "unix:/run/gunicorn.sock"

# --------------------------------------------------------------------
# Workers
# --------------------------------------------------------------------
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
threads = 1
timeout = 30
keepalive = 2

# --------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------
loglevel = "info"

accesslog = "-"    # stdout (systemd captures this)
errorlog = "-"     # stderr

# Or file-based logging:
# accesslog = "/var/log/gunicorn/access.log"
# errorlog = "/var/log/gunicorn/error.log"

# --------------------------------------------------------------------
# Process naming
# --------------------------------------------------------------------
proc_name = "gunicorn-flask-app"

# --------------------------------------------------------------------
# Security / misc
# --------------------------------------------------------------------
preload_app = True
max_requests = 1000
max_requests_jitter = 50

# --------------------------------------------------------------------
# Paths (optional but helpful)
# --------------------------------------------------------------------
chdir = "/home/sam/minimost"

# --------------------------------------------------------------------
# Environment variables (optional)
# --------------------------------------------------------------------

