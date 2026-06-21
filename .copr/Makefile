# Source-RPM builder for Fedora COPR (and local use).
#
# COPR's "make_srpm" source method runs this as:
#
#     make -f .copr/Makefile srpm outdir=<dir> spec=<path>
#
# and expects exactly one .src.rpm to land in $(outdir). On a webhook-triggered
# build COPR clones this repo, runs the target below to produce the SRPM, then
# builds it in a clean mock chroot for each configured Fedora target.
#
# Run it yourself the same way to reproduce what COPR does:
#
#     make -f .copr/Makefile srpm outdir=/tmp/out

outdir ?= $(CURDIR)
spec   ?= minimost.spec

# Run the whole recipe in one shell so the version is read at *runtime*, after
# the build deps are installed. (make expands $(shell)/$(eval) before any recipe
# line runs, which would compute the version before `dnf install`.) The version
# comes straight from the spec's Version field — bump-my-version keeps that in
# lockstep with _version.py (see [tool.bumpversion] in pyproject.toml), so the
# spec is authoritative and needs no stamping here.
.ONESHELL:
srpm:
	set -eu
	dnf -y install --setopt=install_weak_deps=False rpm-build rpmdevtools git sed
	version=$$(sed -n 's/^Version:[[:space:]]*//p' "$(spec)" | head -n1)
	test -n "$$version"
	rm -rf .srpm-build
	mkdir -p .srpm-build/SOURCES .srpm-build/SPECS "$(outdir)"
	cp "$(spec)" .srpm-build/SPECS/minimost.spec
	# Append a %changelog generated from git history (the committed spec has none),
	# so cutting a release never requires a spec edit. See .copr/gen-changelog.sh.
	sh .copr/gen-changelog.sh "$$version" >> .srpm-build/SPECS/minimost.spec
	git archive --format=tar.gz --prefix="minimost-$$version/" \
		-o ".srpm-build/SOURCES/minimost-$$version.tar.gz" HEAD
	rpmbuild -bs .srpm-build/SPECS/minimost.spec \
		--define "_topdir $(CURDIR)/.srpm-build" \
		--define "_sourcedir $(CURDIR)/.srpm-build/SOURCES"
	cp .srpm-build/SRPMS/*.src.rpm "$(outdir)/"

.PHONY: srpm
