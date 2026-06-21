Name:           minimost
# Single source of truth for the version is src/minimost/_version.py. The build
# pipeline (.copr/Makefile and the rpm.yml workflow) rewrites this Version line
# from it before building, so releasing only means bumping _version.py + tagging
# — never editing this spec. The literal below is just a fallback for a direct
# `rpmbuild minimost.spec` and may lag the real version.
Version:        0.0.2
Release:        1%{?dist}
Summary:        Lightweight self-hosted collaboration platform for messaging

# The whole tree is MIT (see LICENSE). The bundled fonts/sounds/images under
# src/minimost/static/ are covered by the same license; if any asset is ever
# added under a different license, switch this to an SPDX expression
# (e.g. "MIT AND CC-BY-4.0") and document the breakdown here.
License:        MIT
URL:            https://github.com/SamuelDonovan/minimost
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

# Pure-Python application: no compiled extensions, so one build serves every arch.
BuildArch:      noarch

BuildRequires:  python3-devel
# The %%pyproject_* macros. Fedora's python3-devel pulls this in implicitly, but
# EPEL/RHEL do not, so require it explicitly for a portable build.
BuildRequires:  pyproject-rpm-macros
# Provides %%{_unitdir} and the %%systemd_* scriptlet macros.
BuildRequires:  systemd-rpm-macros

# MiniMost ships a systemd service that runs the app under gunicorn. gunicorn is
# the production WSGI server (it is NOT a [project] dependency in pyproject.toml,
# so %%pyproject_buildrequires/%%pyproject_save_files will not pull it in — it is
# required here explicitly). Flask is declared in pyproject and is resolved
# automatically by the generated Python dependencies.
Requires:       python3-gunicorn

%description
MiniMost is a small, self-hosted team chat server: channels, direct messages,
file sharing, reactions, message search, and one-to-one voice/video calling
over WebRTC. It depends only on Flask at runtime, stores everything in SQLite,
and serves a dependency-free vanilla-JavaScript web client. A bundled pure-Python
STUN server and an auto-provisioned local TLS certificate make LAN calling work
with no external services.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
# Record the installed package files (including the bundled templates/, static/
# assets and settings.json package-data) so they land in %%files automatically.
%pyproject_save_files minimost

# Ship the systemd unit. It runs as a DynamicUser with StateDirectory=minimost,
# so the package creates neither a system user nor /var/lib/minimost — systemd
# provisions both at first start. That keeps %%files and the scriptlets minimal.
install -D -m 0644 minimost.service %{buildroot}%{_unitdir}/minimost.service

%check
# Lightweight, non-flaky verification that every shipped module imports cleanly
# in the build root. The full pytest/jest suites run in CI rather than here.
# MINIMOST_SKIP_TLS keeps the import from provisioning a TLS cert; gunicorn_conf
# is excluded because it calls ensure_certs() at import time (and pulls gunicorn,
# a runtime-only dependency not present in the build root).
export MINIMOST_SKIP_TLS=1
# Importing the package initialises its SQLite databases as a side effect; point
# the data root at a throwaway dir so the check writes nothing into the buildroot.
export MINIMOST_DATA_DIR="$(mktemp -d)"
%pyproject_check_import -e '*.gunicorn_conf'

%post
%systemd_post minimost.service

%preun
%systemd_preun minimost.service

%postun
%systemd_postun_with_restart minimost.service

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
# Console-script entry point declared in pyproject ([project.scripts]); the
# pyproject macros place it in %%{_bindir} but do not auto-list it.
%{_bindir}/minimost
%{_unitdir}/minimost.service

# No %%changelog here: the build pipeline (.copr/Makefile and the rpm.yml
# workflow) appends one generated from git history by .copr/gen-changelog.sh, so
# releases need no spec edit. When this spec moves to Fedora dist-git, drop the
# generated changelog in favour of %%autochangelog (+ %%autorelease), which dist-git
# expands natively from the packaging repo's own commits.
