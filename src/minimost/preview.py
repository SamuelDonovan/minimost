"""
minimost.preview
================

Link preview generation for URLs posted in chat messages.

When a user sends a message containing a URL, the client fetches a preview
card from ``/link_preview?url=<url>`` and renders it below the message.
This module implements the server-side logic for generating those cards.

Three preview strategies are tried in order:

1. **Bitbucket Cloud** — URLs on ``bitbucket.org``.  Fetches raw file content
   via the Bitbucket Cloud REST API and returns a code snippet with optional
   line-number highlighting.

2. **Bitbucket Server / Data Center** — Self-hosted Bitbucket instances
   matching the ``/projects/{P}/repos/{R}/browse/{path}`` URL pattern.
   Fetches raw content via the Bitbucket Server REST API.

3. **OpenGraph / generic** — Falls back to fetching the HTML page and
   extracting ``<meta property="og:…">`` tags (plus ``<title>`` and Twitter
   card meta tags) to build a rich preview card.

**Security:**

* Private and loopback IP addresses are blocked by :func:`_is_safe_url`
  to prevent Server-Side Request Forgery (SSRF).
* Only ``http`` and ``https`` schemes are accepted.
* A 5-second timeout and 64 KiB read limit are applied to all outgoing
  requests to prevent resource exhaustion.

**Caching:**

Results are cached in an in-process FIFO dictionary (:data:`_CACHE`) with a
maximum of 200 entries.  This is intentionally simple — cache entries are
never invalidated, and the cache is lost on server restart.

Module-level attributes
-----------------------
_CACHE : dict
    In-process preview result cache.  Keys are URL strings; values are the
    result dicts returned by :func:`fetch_preview`.

_CACHE_MAX : int
    Maximum number of entries in :data:`_CACHE` before the oldest entry is
    evicted (FIFO).

_TIMEOUT : int
    HTTP request timeout in seconds (5).

_HEADERS : dict
    Request headers sent with all outgoing HTTP requests, including a
    browser-like ``User-Agent`` to avoid bot-detection blocks.

_PRIVATE_RANGES : re.Pattern
    Regex that matches hostnames known to be private or loopback addresses
    (used as a fast pre-filter before the DNS-based ``_resolves_to_public_ip``
    check).
"""

import re
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

_CACHE = {}
_CACHE_MAX = 200
_TIMEOUT = 5
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MiniMost/1.0)",
    "Accept": "text/html,*/*",
    "Accept-Language": "en-US,en;q=0.5",
}
_BB_CLOUD_HOST = "bitbucket.org"

_TEXT_EXTENSIONS = frozenset(
    {
        "c",
        "cc",
        "cpp",
        "cxx",
        "h",
        "hpp",
        "py",
        "pyw",
        "js",
        "mjs",
        "cjs",
        "jsx",
        "ts",
        "tsx",
        "java",
        "kt",
        "scala",
        "rs",
        "go",
        "rb",
        "php",
        "pl",
        "lua",
        "sh",
        "bash",
        "zsh",
        "fish",
        "cmake",
        "mk",
        "make",
        "groovy",
        "gradle",
        "vhd",
        "vhdl",
        "v",
        "vh",
        "sv",
        "svh",
        "xml",
        "xsl",
        "xslt",
        "xsd",
        "svg",
        "html",
        "htm",
        "css",
        "scss",
        "sass",
        "less",
        "json",
        "yaml",
        "yml",
        "toml",
        "ini",
        "cfg",
        "conf",
        "txt",
        "md",
        "rst",
        "csv",
        "sql",
        "r",
        "swift",
        "m",
        "ex",
        "exs",
        "erl",
        "tf",
        "hcl",
        "proto",
    }
)

_TEXT_FILENAMES = frozenset(
    {
        "dockerfile",
        "makefile",
        "cmakelists.txt",
        "gemfile",
        "rakefile",
        "vagrantfile",
        "procfile",
        "brewfile",
        ".env",
        "requirements.txt",
    }
)


def is_text_filename(name):
    """Return ``True`` if *name* (a basename) denotes a previewable text file.

    Matches by extension (:data:`_TEXT_EXTENSIONS`), by exact filename
    (:data:`_TEXT_FILENAMES`), or by the ``jenkinsfile`` prefix — which covers
    ``Jenkinsfile``, ``Jenkinsfile.prod`` and similar (case-insensitive).
    """
    name = name.lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    return (
        ext in _TEXT_EXTENSIONS
        or name in _TEXT_FILENAMES
        or name.startswith("jenkinsfile")
    )


_PRIVATE_RANGES = re.compile(
    r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|::1)"
)


class _MetaParser(HTMLParser):
    """Streaming HTML parser that extracts page metadata for link previews.

    Parses the ``<head>`` section of an HTML document and collects metadata
    from the following sources (in priority order via ``dict.setdefault``):

    * ``<meta property="og:*">`` — OpenGraph protocol tags.
    * ``<meta name="twitter:title|description|image">`` — Twitter Card tags.
    * ``<meta name="description">`` — generic description tag.
    * ``<title>`` — plain HTML title element (lowest priority).

    Parsing stops immediately when the ``<body>`` tag is encountered, since
    all relevant metadata is in the ``<head>``.  This minimises memory usage
    for large pages.

    Attributes
    ----------
    og : dict
        Collected metadata keyed by OpenGraph property name (without the
        ``og:`` prefix), e.g. ``{"title": "...", "description": "...",
        "image": "..."}``.

    Example::

        parser = _MetaParser()
        parser.feed('<head><meta property="og:title" content="Hello"></head>')
        assert parser.title == "Hello"
    """

    def __init__(self):
        super().__init__()
        self.og = {}
        self._in_title = False
        self._title_buf = []
        self._stop = False

    def handle_starttag(self, tag, attrs):
        """Process an opening HTML tag.

        Stops processing entirely once ``<body>`` is seen.  Extracts content
        from ``<meta>`` tags according to the priority rules described in the
        class docstring.  Sets an internal flag when ``<title>`` is opened.

        :param tag: Lowercase tag name.
        :type tag: str
        :param attrs: List of ``(name, value)`` attribute pairs.
        :type attrs: list of tuple
        """
        if self._stop:
            return
        if tag == "body":
            self._stop = True
            return
        ad = dict(attrs)
        if tag == "meta":
            prop = (ad.get("property") or "").lower()
            name = (ad.get("name") or "").lower()
            content = ad.get("content") or ""
            if prop.startswith("og:"):
                self.og.setdefault(prop[3:], content)
            elif name == "description":
                self.og.setdefault("description", content)
            elif name in ("twitter:title", "twitter:card"):
                self.og.setdefault("title", content)
            elif name == "twitter:description":
                self.og.setdefault("description", content)
            elif name == "twitter:image":
                self.og.setdefault("image", content)
        elif tag == "title":
            self._in_title = True

    def handle_data(self, data):
        """Accumulate text data inside ``<title>`` elements.

        :param data: Raw text content from the parser.
        :type data: str
        """
        if self._in_title:
            self._title_buf.append(data)

    def handle_endtag(self, tag):
        """Clear the title-tracking flag when the ``</title>`` tag is seen.

        :param tag: Lowercase tag name.
        :type tag: str
        """
        if tag == "title":
            self._in_title = False

    @property
    def title(self):
        """The best available title string.

        Returns the OpenGraph/Twitter ``title`` if one was found in
        ``<meta>`` tags, otherwise falls back to the content of the
        ``<title>`` element.

        :rtype: str
        """
        return self.og.get("title") or "".join(self._title_buf).strip()

    @property
    def description(self):
        """The page description from ``<meta>`` tags, or an empty string.

        :rtype: str
        """
        return self.og.get("description", "")

    @property
    def image(self):
        """The preview image URL from ``<meta>`` tags, or an empty string.

        :rtype: str
        """
        return self.og.get("image", "")


def _is_safe_url(url):
    """Check that a URL does not point to a private or loopback address.

    Parses the hostname from *url* and tests it against :data:`_PRIVATE_RANGES`.
    This is the primary SSRF (Server-Side Request Forgery) mitigation: it
    prevents the preview endpoint from being used to probe internal network
    services.

    Blocked address patterns:

    * ``localhost``
    * ``127.x.x.x`` (loopback)
    * ``10.x.x.x`` (RFC 1918 private)
    * ``172.16–31.x.x`` (RFC 1918 private)
    * ``192.168.x.x`` (RFC 1918 private)
    * ``::1`` (IPv6 loopback)

    :param url: The URL to validate.
    :type url: str
    :returns: ``True`` if the URL is safe to fetch, ``False`` if it
        resolves to a private/loopback address or cannot be parsed.
    :rtype: bool
    """
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    return not _PRIVATE_RANGES.match(host)


def _resolves_to_public_ip(hostname):
    """Return True if *hostname* resolves only to public IP addresses."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        return False

    if not infos:
        return False

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False

    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect hop against the SSRF allowlist.

    ``urlopen`` follows 3xx redirects automatically and re-resolves the new
    host *without* the public-IP check that guards the initial request. Without
    this, a public URL could ``302`` to ``http://127.0.0.1/`` (or any LAN
    address) and the server would happily fetch it — turning the preview
    endpoint into an SSRF pivot. Each redirect target is held to the same
    scheme and public-IP rules as the first request; anything else aborts the
    fetch.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise urllib.error.HTTPError(
                newurl, code, "unsafe redirect target", headers, fp
            )
        if not _resolves_to_public_ip(parsed.hostname):
            raise urllib.error.HTTPError(
                newurl, code, "unsafe redirect target", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Opener that enforces the redirect allowlist above. Used instead of the bare
# ``urllib.request.urlopen`` (which installs the default, unchecked redirect
# handler) for every outbound preview fetch.
_OPENER = urllib.request.build_opener(_SafeRedirectHandler)


def _fetch(url, max_bytes=65536):
    """Fetch the body of an HTTP/HTTPS URL with safety limits.

    Sends a GET request using :data:`_HEADERS` (browser-like User-Agent)
    and :data:`_TIMEOUT` second timeout.  Reads at most *max_bytes* bytes
    from the response body.

    Only ``http`` and ``https`` schemes are accepted; any other scheme raises
    :exc:`ValueError`.

    :param url: The URL to fetch.
    :type url: str
    :param max_bytes: Maximum number of bytes to read from the response.
        Defaults to 65536 (64 KiB).  Use a larger value when fetching raw
        source files for code previews.
    :type max_bytes: int
    :returns: Raw response body bytes.
    :rtype: bytes
    :raises ValueError: If the URL scheme is not ``http`` or ``https``.
    :raises urllib.error.URLError: If the request fails (network error,
        DNS failure, etc.).
    :raises urllib.error.HTTPError: If the server returns a non-2xx status.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme: {url}")
    if not parsed.hostname:
        raise ValueError(f"Missing host: {url}")
    if not _resolves_to_public_ip(parsed.hostname):
        raise ValueError(f"Unsafe URL: {url}")

    netloc = parsed.hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    safe_url = urllib.parse.urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )

    req = urllib.request.Request(safe_url, headers=_HEADERS)
    # _OPENER re-checks every redirect hop (see _SafeRedirectHandler) so a
    # public URL can't bounce the request to an internal address.
    with _OPENER.open(req, timeout=_TIMEOUT) as resp:  # nosec B310
        return resp.read(max_bytes)


def _build_code_result(raw, filepath, line_start, line_end, url):
    """Build a code preview result dict from raw file text.

    Shared by both Bitbucket Cloud and Bitbucket Server preview functions.
    Slices the file content to show a relevant snippet and annotates it with
    metadata needed for client-side syntax highlighting and line-number display.

    **Snippet selection:**

    * If *line_start* is provided: shows the highlighted line(s) plus
      ±3 lines of context.
    * If *line_start* is ``None``: shows the first 25 lines of the file.

    :param raw: The full raw text content of the file (UTF-8 decoded).
    :type raw: str
    :param filepath: The file path within the repository
        (e.g. ``"src/minimost/chat.py"``).
    :type filepath: str
    :param line_start: 1-based start line to highlight, or ``None`` for no
        highlighting.
    :type line_start: int or None
    :param line_end: 1-based end line to highlight (inclusive), or ``None``
        if only one line is highlighted.
    :type line_end: int or None
    :param url: The original browser URL that triggered the preview, used
        to link back from the preview card.
    :type url: str
    :returns: A code preview dict with keys:

        * ``type`` (str): Always ``"code"``.
        * ``filename`` (str): Basename of the file.
        * ``filepath`` (str): Full repository path.
        * ``language`` (str): File extension (lowercase), used for syntax
          highlighting (e.g. ``"py"``, ``"js"``).
        * ``first_line_num`` (int): Line number of the first line in
          *code* snippet (1-based).
        * ``highlight_start`` (int or None): First highlighted line.
        * ``highlight_end`` (int or None): Last highlighted line.
        * ``code`` (str): Newline-joined snippet text.
        * ``total_lines`` (int): Total number of lines in the full file.
        * ``url`` (str): Original browser URL.
    :rtype: dict
    """
    all_lines = raw.splitlines()
    total = len(all_lines)
    filename = filepath.rsplit("/", 1)[-1]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    _MAX_LINES = 1000
    if line_start is not None:
        ctx = _MAX_LINES // 2
        show_start = max(0, line_start - 1 - ctx)
        show_end = min(total, show_start + _MAX_LINES)
        snippet = all_lines[show_start:show_end]
        first_num = show_start + 1
    else:
        snippet = all_lines[:_MAX_LINES]
        first_num = 1

    return {
        "type": "code",
        "filename": filename,
        "filepath": filepath,
        "language": ext,
        "first_line_num": first_num,
        "highlight_start": line_start,
        "highlight_end": line_end,
        "code": "\n".join(snippet),
        "total_lines": total,
        "url": url,
    }


# ── Bitbucket Cloud (bitbucket.org) ──────────────────────────────────────────
# URL:  https://bitbucket.org/{workspace}/{repo}/src/{ref}/{path}[#lines-N[:M]]
# API:  https://api.bitbucket.org/2.0/repositories/{workspace}/{repo}/src/{ref}/{path}


def _parse_bb_cloud(url):
    """Parse a Bitbucket Cloud file URL into its components.

    Accepts URLs of the form::

        https://bitbucket.org/{workspace}/{repo}/src/{ref}/{path}[#lines-N[:M]]

    :param url: The Bitbucket Cloud URL to parse.
    :type url: str
    :returns: A tuple ``(workspace, repo, ref, filepath, line_start, line_end)``
        if the URL matches, or ``None`` if it does not.

        * ``workspace`` (str): Bitbucket workspace/organization slug.
        * ``repo`` (str): Repository slug.
        * ``ref`` (str): Git ref (branch, tag, or commit SHA).
        * ``filepath`` (str): Path to the file within the repository.
        * ``line_start`` (int or None): 1-based start line from the fragment.
        * ``line_end`` (int or None): 1-based end line from the fragment.
    :rtype: tuple or None
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in (_BB_CLOUD_HOST, f"www.{_BB_CLOUD_HOST}"):
        return None
    parts = parsed.path.lstrip("/").split("/", 4)
    if len(parts) < 5 or parts[2] != "src":
        return None
    workspace, repo, _, ref, filepath = parts
    line_start = line_end = None
    m = re.match(r"lines-(\d+)(?::(\d+))?", parsed.fragment or "")
    if m:
        line_start = int(m.group(1))
        line_end = int(m.group(2)) if m.group(2) else line_start
    return workspace, repo, ref, filepath, line_start, line_end


def _bitbucket_cloud_preview(url):
    """Generate a code preview for a Bitbucket Cloud file URL.

    Calls :func:`_parse_bb_cloud` to validate and decompose the URL, then
    fetches up to 512 KiB of the raw file content from the Bitbucket Cloud
    REST API::

        https://api.bitbucket.org/2.0/repositories/{workspace}/{repo}/src/{ref}/{path}

    Passes the raw text to :func:`_build_code_result` to produce the final
    preview dict.

    :param url: A Bitbucket Cloud file browser URL.
    :type url: str
    :returns: A code preview dict (see :func:`_build_code_result`) on
        success, or ``{}`` if the URL does not match or the API call fails.
    :rtype: dict
    """
    info = _parse_bb_cloud(url)
    if not info:
        return {}
    workspace, repo, ref, filepath, line_start, line_end = info
    api_url = "https://api.bitbucket.org/2.0/repositories/{}/{}/src/{}/{}".format(
        workspace, repo, ref, filepath
    )
    try:
        raw = _fetch(api_url, max_bytes=512 * 1024).decode("utf-8", errors="replace")
    except Exception:
        return {}
    return _build_code_result(raw, filepath, line_start, line_end, url)


# ── Bitbucket Server / Data Center (self-hosted) ─────────────────────────────
# URL:  http(s)://{host}/projects/{PROJECT}/repos/{repo}/browse/{path}[#{start}-{end}]
# API:  http(s)://{host}/rest/api/1.0/projects/{PROJECT}/repos/{repo}/raw/{path}
# The scheme is inherited from the URL, so plain http:// works fine.


def _parse_bb_server(url):
    """Parse a Bitbucket Server / Data Center file URL into its components.

    Accepts URLs of the form::

        http(s)://{host}/projects/{PROJECT}/repos/{repo}/browse/{path}[#{start}-{end}]

    The URL scheme (``http`` or ``https``) is preserved in the returned base
    URL so that plain-HTTP self-hosted instances work correctly.

    :param url: The Bitbucket Server URL to parse.
    :type url: str
    :returns: A tuple ``(base, project, repo, filepath, line_start, line_end)``
        if the URL matches, or ``None`` if it does not.

        * ``base`` (str): Scheme and host, e.g. ``"https://bitbucket.example.com"``.
        * ``project`` (str): Project key.
        * ``repo`` (str): Repository slug.
        * ``filepath`` (str): Path to the file within the repository.
        * ``line_start`` (int or None): 1-based start line from the fragment.
        * ``line_end`` (int or None): 1-based end line from the fragment.
    :rtype: tuple or None
    """
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.lstrip("/").split("/", 5)
    # Expected: ["projects", PROJECT, "repos", REPO, "browse", filepath]
    if (
        len(parts) < 6
        or parts[0] != "projects"
        or parts[2] != "repos"
        or parts[4] != "browse"
    ):
        return None
    project, repo, filepath = parts[1], parts[3], parts[5]
    if not filepath:
        return None
    line_start = line_end = None
    m = re.match(r"^(\d+)(?:-(\d+))?$", parsed.fragment or "")
    if m:
        line_start = int(m.group(1))
        line_end = int(m.group(2)) if m.group(2) else line_start
    base = "{}://{}".format(parsed.scheme, parsed.netloc)
    return base, project, repo, filepath, line_start, line_end


def _bitbucket_server_preview(url):
    """Generate a code preview for a Bitbucket Server / Data Center file URL.

    Calls :func:`_parse_bb_server` to validate and decompose the URL, then
    fetches up to 512 KiB of the raw file content from the Bitbucket Server
    REST API::

        {scheme}://{host}/rest/api/1.0/projects/{PROJECT}/repos/{repo}/raw/{path}

    The URL scheme is inherited from the original URL, so self-hosted HTTP
    instances work without modification.

    :param url: A Bitbucket Server browse URL.
    :type url: str
    :returns: A code preview dict (see :func:`_build_code_result`) on
        success, or ``{}`` if the URL does not match or the API call fails.
    :rtype: dict
    """
    info = _parse_bb_server(url)
    if not info:
        return {}
    base, project, repo, filepath, line_start, line_end = info
    api_url = "{}/rest/api/1.0/projects/{}/repos/{}/raw/{}".format(
        base, project, repo, filepath
    )
    try:
        raw = _fetch(api_url, max_bytes=512 * 1024).decode("utf-8", errors="replace")
    except Exception:
        return {}
    return _build_code_result(raw, filepath, line_start, line_end, url)


def _og_preview(url):
    """Generate a generic OpenGraph preview for any web URL.

    Fetches up to 64 KiB of the page HTML (the default :func:`_fetch` limit)
    and parses it with :class:`_MetaParser`.  If no title can be extracted,
    returns ``{}`` — it is not useful to render a preview card without a title.

    Title and description are capped at 200 and 400 characters respectively
    to prevent excessively large preview cards.

    :param url: The URL to generate a preview for.
    :type url: str
    :returns: An OpenGraph preview dict with keys ``type``, ``title``,
        ``description``, ``image``, ``domain``, and ``url``, or ``{}`` if
        the request fails or no title is found.
    :rtype: dict
    """
    try:
        html = _fetch(url).decode("utf-8", errors="replace")
    except Exception:
        return {}

    parser = _MetaParser()
    parser.feed(html)

    title = parser.title
    if not title:
        return {}

    domain = urllib.parse.urlparse(url).netloc
    return {
        "type": "og",
        "title": title[:200],
        "description": parser.description[:400],
        "image": parser.image,
        "domain": domain,
        "url": url,
    }


def _text_file_preview(url):
    """Generate a code preview for a direct link to a text/source file.

    Checks the URL path's file extension (or filename) against
    :data:`_TEXT_EXTENSIONS` / :data:`_TEXT_FILENAMES`.  If it matches,
    fetches the raw content and passes it through :func:`_build_code_result`.

    :param url: The URL to inspect and potentially fetch.
    :type url: str
    :returns: A code preview dict on success, or ``{}`` if the URL does not
        point to a recognised text file or the fetch fails.
    :rtype: dict
    """
    parsed = urllib.parse.urlparse(url)
    filename = parsed.path.rstrip("/").rsplit("/", 1)[-1]

    if not is_text_filename(filename):
        return {}

    filepath = parsed.path.lstrip("/") or filename
    try:
        raw = _fetch(url, max_bytes=512 * 1024).decode("utf-8", errors="replace")
    except Exception:
        return {}

    return _build_code_result(raw, filepath, None, None, url)


def fetch_preview(url):
    """Return a preview dict for a URL, using the cache when available.

    This is the main entry point called by the ``/link_preview`` route in
    :mod:`minimost.chat`.

    **Strategy (tried in order):**

    1. Return the cached result if *url* is already in :data:`_CACHE`.
    2. Reject the URL if the scheme is not ``http``/``https``, or if
       :func:`_is_safe_url` returns ``False`` (SSRF protection).
    3. Try :func:`_bitbucket_cloud_preview` if the host is ``bitbucket.org``.
    4. Try :func:`_bitbucket_server_preview` if the URL matches the
       Bitbucket Server path pattern.
    5. Fall back to :func:`_og_preview` for any other URL.
    6. Cache the result (even ``{}``) and return it.

    **FIFO cache eviction:**

    When the cache reaches :data:`_CACHE_MAX` entries, the oldest entry is
    removed by deleting the first key from the dictionary (relies on Python
    3.7+ insertion-ordered dicts).

    :param url: The URL to preview.
    :type url: str
    :returns: A preview dict (see the route docstring for key details), or
        ``{}`` if no preview could be generated.
    :rtype: dict
    """
    if url in _CACHE:
        return _CACHE[url]

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {}
    if not _is_safe_url(url):
        return {}

    if parsed.netloc in (_BB_CLOUD_HOST, f"www.{_BB_CLOUD_HOST}"):
        result = _bitbucket_cloud_preview(url)
    elif _parse_bb_server(url) is not None:
        result = _bitbucket_server_preview(url)
    else:
        result = _text_file_preview(url)

    if not result:
        result = _og_preview(url)

    # FIFO eviction
    if len(_CACHE) >= _CACHE_MAX:
        del _CACHE[next(iter(_CACHE))]

    _CACHE[url] = result
    return result
