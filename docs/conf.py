# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# Make the minimost package importable from the source tree so that
# sphinx.ext.autodoc can import and introspect the modules.
sys.path.insert(0, os.path.abspath("../src"))

# -- Project information -----------------------------------------------------

project = "MiniMost"
copyright = "2024, Samuel Mehalko"
author = "Samuel Mehalko"
release = "0.1.0"

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",  # Generate docs from docstrings
    "sphinx.ext.napoleon",  # Support Google/NumPy style docstrings
    "sphinx.ext.viewcode",  # Add [source] links to autodoc output
    "sphinx.ext.intersphinx",  # Cross-reference to external docs
    "sphinxcontrib.httpdomain",  # HTTP route directives (.. http:get::, etc.)
]

# autodoc settings
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "special-members": "__init__",
}
autodoc_member_order = "bysource"
autoclass_content = "both"

# napoleon settings (Google-style docstring support)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_use_param = True
napoleon_use_rtype = True

# intersphinx: link to Python standard library and Flask docs
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "flask": ("https://flask.palletsprojects.com/en/stable/", None),
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"

# Fallback to the built-in alabaster theme if sphinx_rtd_theme is not
# installed — install it with: pip install sphinx-rtd-theme
try:
    import sphinx_rtd_theme  # noqa: F401
except ImportError:
    html_theme = "alabaster"

html_static_path = ["_static"]

# -- Options for autodoc -----------------------------------------------------


# Do not skip private members that have docstrings
def skip_member(app, what, name, obj, skip, options):
    if name.startswith("_") and not name.startswith("__"):
        # Include private functions/methods that have a non-trivial docstring
        doc = getattr(obj, "__doc__", "") or ""
        if len(doc.strip()) > 30:
            return False
    return skip


def setup(app):
    app.connect("autodoc-skip-member", skip_member)
