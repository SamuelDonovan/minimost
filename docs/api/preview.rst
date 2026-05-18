minimost.preview
================

.. automodule:: minimost.preview
   :members:
   :undoc-members: False
   :show-inheritance:

Preview Type Reference
----------------------

**Code preview** (returned for Bitbucket URLs):

.. code-block:: python

    {
        "type": "code",
        "filename": "chat.py",          # basename of the file
        "filepath": "src/chat.py",      # full path within the repo
        "language": "py",               # file extension (for highlighting)
        "first_line_num": 47,           # line number of the first snippet line
        "highlight_start": 50,          # first highlighted line (1-based), or None
        "highlight_end": 60,            # last highlighted line (1-based), or None
        "code": "def send(channel):\n...",  # snippet text
        "total_lines": 616,             # total lines in the full file
        "url": "https://bitbucket.org/...", # original URL
    }

**OpenGraph preview** (returned for generic web pages):

.. code-block:: python

    {
        "type": "og",
        "title": "Page Title",          # truncated to 200 chars
        "description": "...",           # truncated to 400 chars
        "image": "https://...",         # og:image URL
        "domain": "example.com",        # hostname only
        "url": "https://example.com/page",  # original URL
    }

**No preview available**:

.. code-block:: python

    {}

Supported Bitbucket URL Formats
--------------------------------

**Bitbucket Cloud:**

.. code-block:: text

    https://bitbucket.org/{workspace}/{repo}/src/{ref}/{path}
    https://bitbucket.org/{workspace}/{repo}/src/{ref}/{path}#lines-N
    https://bitbucket.org/{workspace}/{repo}/src/{ref}/{path}#lines-N:M

**Bitbucket Server / Data Center:**

.. code-block:: text

    https://{host}/projects/{PROJECT}/repos/{repo}/browse/{path}
    https://{host}/projects/{PROJECT}/repos/{repo}/browse/{path}#{line}
    https://{host}/projects/{PROJECT}/repos/{repo}/browse/{path}#{start}-{end}
    http://{host}/projects/{PROJECT}/repos/{repo}/browse/{path}   (plain HTTP also works)
