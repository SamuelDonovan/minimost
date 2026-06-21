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
# line runs, so computing the version that way executed before `dnf install` and
# yielded an empty string in COPR's minimal SRPM chroot.) The version is parsed
# from _version.py with sed — no python3 needed in the SRPM buildroot.
.ONESHELL:
srpm:
	set -eu
	dnf -y install --setopt=install_weak_deps=False rpm-build rpmdevtools git sed
	version=$$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/minimost/_version.py)
	test -n "$$version"
	rm -rf .srpm-build
	mkdir -p .srpm-build/SOURCES .srpm-build/SPECS "$(outdir)"
	# Keep src/minimost/_version.py the single source of truth: stamp the spec's
	# Version to match so Source0's minimost-<version>.tar.gz name always lines up,
	# even if the committed spec's Version drifts behind a version bump.
	sed "s/^Version:.*/Version:        $$version/" "$(spec)" > .srpm-build/SPECS/minimost.spec
	git archive --format=tar.gz --prefix="minimost-$$version/" \
		-o ".srpm-build/SOURCES/minimost-$$version.tar.gz" HEAD
	rpmbuild -bs .srpm-build/SPECS/minimost.spec \
		--define "_topdir $(CURDIR)/.srpm-build" \
		--define "_sourcedir $(CURDIR)/.srpm-build/SOURCES"
	cp .srpm-build/SRPMS/*.src.rpm "$(outdir)/"

.PHONY: srpm
