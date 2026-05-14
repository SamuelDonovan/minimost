import re
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

_PRIVATE_RANGES = re.compile(
    r"^(localhost|127\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|::1)"
)


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og = {}
        self._in_title = False
        self._title_buf = []
        self._stop = False

    def handle_starttag(self, tag, attrs):
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
        if self._in_title:
            self._title_buf.append(data)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    @property
    def title(self):
        return self.og.get("title") or "".join(self._title_buf).strip()

    @property
    def description(self):
        return self.og.get("description", "")

    @property
    def image(self):
        return self.og.get("image", "")


def _is_safe_url(url):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    return not _PRIVATE_RANGES.match(host)


def _fetch(url, max_bytes=65536):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read(max_bytes)


def _build_code_result(raw, filepath, line_start, line_end, url):
    """Shared helper: slice raw file content and build the code preview dict."""
    all_lines = raw.splitlines()
    total = len(all_lines)
    filename = filepath.rsplit("/", 1)[-1]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if line_start is not None:
        ctx = 3
        show_start = max(0, line_start - 1 - ctx)
        show_end = min(total, (line_end or line_start) + ctx)
        snippet = all_lines[show_start:show_end]
        first_num = show_start + 1
    else:
        snippet = all_lines[:25]
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
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in ("bitbucket.org", "www.bitbucket.org"):
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
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.lstrip("/").split("/", 5)
    # Expected: ["projects", PROJECT, "repos", REPO, "browse", filepath]
    if (len(parts) < 6
            or parts[0] != "projects"
            or parts[2] != "repos"
            or parts[4] != "browse"):
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


def fetch_preview(url):
    if url in _CACHE:
        return _CACHE[url]

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {}
    if not _is_safe_url(url):
        return {}

    if parsed.netloc in ("bitbucket.org", "www.bitbucket.org"):
        result = _bitbucket_cloud_preview(url)
    elif _parse_bb_server(url) is not None:
        result = _bitbucket_server_preview(url)
    else:
        result = {}

    if not result:
        result = _og_preview(url)

    # FIFO eviction
    if len(_CACHE) >= _CACHE_MAX:
        del _CACHE[next(iter(_CACHE))]

    _CACHE[url] = result
    return result
