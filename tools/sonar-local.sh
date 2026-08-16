#!/usr/bin/env bash
#
# Run the SonarQube analysis locally, against a SonarQube Community Build
# container, and fail if the changes about to be pushed introduce an issue.
#
# Why this exists: the pre-commit hooks cover black/ruff/bandit/eslint/prettier
# and the two test suites, but none of them implement a single Sonar rule. The
# HTML (Web:*), CSS and Python Sonar rules in particular have no standalone
# linter equivalent, so the only way to see them before a push is to run the
# real analyzers. eslint-plugin-sonarjs (wired into eslint.config.mjs) already
# covers the JavaScript side in ~4s on every commit; this script covers the
# rest, and is wired to pre-push because a scan costs ~40s.
#
# The local server uses the stock "Sonar way" quality profiles — the same ones
# SamuelDonovan_minimost uses on SonarCloud — so findings line up. Verified
# 2026-08-15: a local scan reproduced SonarCloud's python:S1192 x2, css:S7924 x2
# and the 8 Web:* findings at identical lines.
#
# Gating: SonarQube Community Build has no branch analysis, so it cannot
# reproduce SonarCloud's "new code" period directly. Instead this script
# intersects the issue list with the lines you actually touched relative to
# $SONAR_BASE (default origin/main), which is the same question the CI gate
# asks. Pre-existing issues elsewhere in the tree never block a push.
#
# Usage:
#   tools/sonar-local.sh            # scan, gate on lines changed vs origin/main
#   SONAR_BASE=HEAD~3 tools/...     # gate against a different base
#   SONAR_LOCAL_ALL=1 tools/...     # report every issue, not just changed lines
#
# One-time setup is automatic: the script starts the container and provisions a
# scanner token, caching it in ~/.config/minimost/. Set SONAR_LOCAL_TOKEN to
# use your own instead.

set -euo pipefail

CONTAINER=minimost-sonar
IMAGE=sonarqube:community
HOST_URL=${SONAR_LOCAL_URL:-http://localhost:9000}
PROJECT_KEY=minimost-local
BASE=${SONAR_BASE:-origin/main}
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/minimost"
TOKEN_FILE="$CONFIG_DIR/sonar-local.token"
ADMIN_PASS_FILE="$CONFIG_DIR/sonar-local.admin"

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

die() {
	echo "sonar-local: $*" >&2
	exit 1
}

# --- docker -----------------------------------------------------------------
docker info >/dev/null 2>&1 || die "docker daemon is not running (sudo systemctl start docker).
If it fails to start right after a kernel upgrade, reboot: the running kernel's
modules are deleted by the upgrade, so nf_tables/overlay can no longer load."

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
	if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
		echo "sonar-local: starting existing $CONTAINER container..."
		docker start "$CONTAINER" >/dev/null
	else
		echo "sonar-local: creating $CONTAINER container (first run pulls $IMAGE)..."
		docker run -d --name "$CONTAINER" -p 9000:9000 \
			-v minimost-sonar-data:/opt/sonarqube/data \
			-v minimost-sonar-ext:/opt/sonarqube/extensions \
			-v minimost-sonar-logs:/opt/sonarqube/logs \
			"$IMAGE" >/dev/null
	fi
fi

printf 'sonar-local: waiting for SonarQube'
for _ in $(seq 1 60); do
	status=$(curl -fsS -m 5 "$HOST_URL/api/system/status" 2>/dev/null |
		python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)
	[ "$status" = "UP" ] && break
	printf '.'
	sleep 5
done
echo
[ "${status:-}" = "UP" ] || die "SonarQube did not come up at $HOST_URL (docker logs $CONTAINER)"

# --- token ------------------------------------------------------------------
# Provisioned once and cached outside the repo so a clean checkout keeps working.
mkdir -p "$CONFIG_DIR"
if [ -n "${SONAR_LOCAL_TOKEN:-}" ]; then
	token=$SONAR_LOCAL_TOKEN
elif [ -s "$TOKEN_FILE" ]; then
	token=$(cat "$TOKEN_FILE")
else
	echo "sonar-local: provisioning a scanner token..."
	if [ -s "$ADMIN_PASS_FILE" ]; then
		admin_pass=$(cat "$ADMIN_PASS_FILE")
	else
		# SonarQube refuses to stay on the default admin/admin, so rotate it to a
		# generated password on first run and remember it.
		admin_pass=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
		curl -fsS -u admin:admin -X POST "$HOST_URL/api/users/change_password" \
			-d "login=admin" --data-urlencode "previousPassword=admin" \
			--data-urlencode "password=$admin_pass" >/dev/null ||
			die "could not set the admin password. If you already changed it, put it in $ADMIN_PASS_FILE"
		(
			umask 077
			printf '%s' "$admin_pass" >"$ADMIN_PASS_FILE"
		)
	fi
	token=$(curl -fsS -u "admin:$admin_pass" -X POST "$HOST_URL/api/user_tokens/generate" \
		-d "name=minimost-local-$(date +%s)" |
		python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
	(
		umask 077
		printf '%s' "$token" >"$TOKEN_FILE"
	)
fi

# --- coverage ---------------------------------------------------------------
# sonar-project.properties points at coverage.xml and coverage/js/lcov.info.
# Missing reports only cost coverage metrics, not issues, so warn rather than
# fail — a pre-push hook has no business running the ~6min pytest suite.
[ -f coverage.xml ] || echo "sonar-local: note: no coverage.xml (run pytest to include Python coverage)"
[ -f coverage/js/lcov.info ] || echo "sonar-local: note: no JS lcov (run 'npx jest --coverage')"

# --- scan -------------------------------------------------------------------
# sonar.organization is a SonarCloud-only concept; blank it for the local server.
echo "sonar-local: scanning..."
SONAR_TOKEN=$token npx --no-install sonar-scanner-npm \
	-Dsonar.host.url="$HOST_URL" \
	-Dsonar.projectKey="$PROJECT_KEY" \
	-Dsonar.projectName=MiniMost-local \
	-Dsonar.organization= \
	-Dsonar.scm.exclusions.disabled=true \
	>/tmp/sonar-local-scan.log 2>&1 ||
	{
		tail -30 /tmp/sonar-local-scan.log
		die "scan failed (full log: /tmp/sonar-local-scan.log)"
	}

# The scanner returns as soon as the report is uploaded; the server still has to
# process it before the issue list reflects this analysis.
for _ in $(seq 1 40); do
	pending=$(curl -fsS -u "$token:" "$HOST_URL/api/ce/component?component=$PROJECT_KEY" |
		python3 -c 'import json,sys; d=json.load(sys.stdin); print(1 if d.get("queue") else 0)')
	[ "$pending" = "0" ] && break
	sleep 3
done

# --- report -----------------------------------------------------------------
curl -fsS -u "$token:" \
	"$HOST_URL/api/issues/search?componentKeys=$PROJECT_KEY&resolved=false&ps=500" \
	>/tmp/sonar-local-issues.json

if [ -n "${SONAR_LOCAL_ALL:-}" ]; then
	changed_lines=""
else
	# "file:line" for every line added or modified relative to the base ref, which
	# is as close as Community Build gets to SonarCloud's new-code period.
	git fetch --quiet origin main 2>/dev/null || true
	base_ref=$BASE
	git rev-parse --verify --quiet "$base_ref" >/dev/null || base_ref=$(git rev-parse HEAD)
	changed_lines=$(git diff -U0 "$base_ref" -- . |
		awk '/^\+\+\+ b\// { f = substr($0, 7) }
		     /^@@/ { split($3, a, ","); s = substr(a[1], 2) + 0; n = (a[2] == "" ? 1 : a[2] + 0);
		             for (i = 0; i < n; i++) print f ":" (s + i) }')
	# git diff never mentions untracked files, so a brand-new file would sail
	# through the gate on a manual run. Count every one of its lines as changed.
	while IFS= read -r f; do
		[ -n "$f" ] || continue
		awk -v f="$f" 'END { for (i = 1; i <= NR; i++) print f ":" i }' "$f"
	done < <(git ls-files --others --exclude-standard) >/tmp/sonar-local-untracked.txt
	changed_lines=$(printf '%s\n%s' "$changed_lines" "$(cat /tmp/sonar-local-untracked.txt)")
fi

CHANGED="$changed_lines" SHOW_ALL="${SONAR_LOCAL_ALL:-}" python3 - <<'PY'
import json, os, sys

issues = json.load(open("/tmp/sonar-local-issues.json"))["issues"]
show_all = bool(os.environ.get("SHOW_ALL"))
changed = set(os.environ.get("CHANGED", "").split())

blocking, other = [], []
for i in issues:
    path = i["component"].split(":", 1)[-1]
    line = i.get("line")
    key = f"{path}:{line}"
    (blocking if show_all or key in changed else other).append((path, line, i))

def show(rows):
    for path, line, i in sorted(rows, key=lambda r: (r[0], r[1] or 0)):
        print(f"  {i['rule']:<38} {path}:{line}\n      {i['message']}")

if blocking:
    print(f"\nsonar-local: {len(blocking)} issue(s) on lines you changed:\n")
    show(blocking)
    print(f"\n{len(other)} pre-existing issue(s) elsewhere were ignored.")
    print("Dashboard: http://localhost:9000/dashboard?id=minimost-local")
    sys.exit(1)

print(f"\nsonar-local: clean — no Sonar issues on changed lines "
      f"({len(other)} pre-existing elsewhere).")
print("Dashboard: http://localhost:9000/dashboard?id=minimost-local")
PY
