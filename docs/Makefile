# Minimal Makefile for Sphinx documentation.
# Run `make html` from this directory to build the docs.

SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

.PHONY: help clean html dirhtml singlehtml

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  html        Build HTML documentation (default)"
	@echo "  dirhtml     Build HTML in a directory-per-page layout"
	@echo "  singlehtml  Build a single HTML page"
	@echo "  clean       Remove the _build directory"
	@echo ""
	@echo "Prerequisites:"
	@echo "  pip install sphinx sphinx-rtd-theme"

html:
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
	@echo ""
	@echo "Build finished. Open _build/html/index.html in a browser."

dirhtml:
	@$(SPHINXBUILD) -M dirhtml "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

singlehtml:
	@$(SPHINXBUILD) -M singlehtml "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

clean:
	@$(SPHINXBUILD) -M clean "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
