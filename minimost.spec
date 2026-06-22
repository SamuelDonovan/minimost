Name:           minimost
# Do not edit Version by hand. `bump-my-version bump <part>` (config in
# .bumpversion.toml) updates this line, src/minimost/_version.py, setup.cfg, and
# the tag together, so they never drift. The build reads the version from here.
Version:        0.0.3
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

%if 0%{?rhel} && 0%{?rhel} < 9
# EL8's rpm (4.14) predates dynamic BuildRequires (%%generate_buildrequires, rpm
# >= 4.15), so the deps %%pyproject_buildrequires would generate on newer distros
# are listed statically here instead. python3-flask is needed by the %%check
# import smoke test (and is EL8's runtime Flask, from AppStream).
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  python3-pip
BuildRequires:  python3-flask
%endif

# MiniMost ships a systemd service that runs the app under gunicorn. gunicorn is
# the production WSGI server (it is NOT a setup.cfg install_requires, so the
# automatic Python dependency generator won't add it) — require it explicitly.
# Flask is declared in setup.cfg and is resolved automatically from the wheel
# metadata by the dependency generator on Fedora/EL9+.
Requires:       python3-gunicorn

%if 0%{?rhel} && 0%{?rhel} < 9
# EL8's dependency generator does not reliably emit python3dist(flask) from the
# installed wheel, so require Flask explicitly there.
Requires:       python3-flask
%endif

%description
MiniMost is a small, self-hosted team chat server: channels, direct messages,
file sharing, reactions, message search, and one-to-one voice/video calling
over WebRTC. It depends only on Flask at runtime, stores everything in SQLite,
and serves a dependency-free vanilla-JavaScript web client. A bundled pure-Python
STUN server and an auto-provisioned local TLS certificate make LAN calling work
with no external services.

%prep
%autosetup -n %{name}-%{version}

# Dynamic BuildRequires only where rpm supports the section (Fedora, EL9+). On
# EL8 the build deps are listed statically above instead.
%if 0%{?fedora} || 0%{?rhel} >= 9
%generate_buildrequires
%pyproject_buildrequires
%endif

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
# Lightweight, non-flaky smoke test that the installed package imports cleanly.
# A plain `python -c import` (rather than %%pyproject_check_import, whose -e flag
# is absent from EL8's old pyproject-rpm-macros) keeps this portable across every
# target. MINIMOST_SKIP_TLS stops the import from provisioning a TLS cert
# (gunicorn_conf honours it); MINIMOST_DATA_DIR points the import-time SQLite
# bootstrap at a throwaway dir so nothing is written into the buildroot.
export MINIMOST_SKIP_TLS=1
export MINIMOST_DATA_DIR="$(mktemp -d)"
PYTHONPATH=%{buildroot}%{python3_sitelib} %{python3} -c "import minimost, minimost.gunicorn_conf, minimost.certs, minimost.stun, minimost.clean, minimost.preview"

%post
%systemd_post minimost.service

%preun
%systemd_preun minimost.service

%postun
%systemd_postun_with_restart minimost.service

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
# Console-script entry point declared in setup.cfg ([options.entry_points]); the
# pyproject macros place it in %%{_bindir} but do not auto-list it.
%{_bindir}/minimost
%{_unitdir}/minimost.service

# No %%changelog here: the build pipeline (.copr/Makefile and the rpm.yml
# workflow) appends one generated from git history by .copr/gen-changelog.sh, so
# releases need no spec edit. When this spec moves to Fedora dist-git, drop the
# generated changelog in favour of %%autochangelog (+ %%autorelease), which dist-git
# expands natively from the packaging repo's own commits.
