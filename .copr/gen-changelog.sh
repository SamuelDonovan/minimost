#!/bin/sh
# Generate an RPM %changelog section from git history.
#
#   Usage: gen-changelog.sh <build-version>
#
# Emits a complete "%changelog" section to stdout, newest entry first:
#   * one entry per release tag (vX.Y.Z), and
#   * a top entry for <build-version> when HEAD is ahead of the newest tag
#     (an untagged / snapshot build).
#
# Each entry's bullets are the user-facing conventional commits (feat/fix/perf)
# in that release's commit range; a release with none gets a single
# "Initial release" line. Scoping to release tags and meaningful commit types is
# what keeps this clean — it does NOT replay every commit in the (mono)repo the
# way rpmautospec's %autochangelog would when the spec lives outside dist-git.
#
# The committed spec carries no %changelog; the build pipeline appends this
# script's output, so cutting a release never requires editing the spec.
set -eu
export LC_ALL=C

build_version="${1:-0.0.0}"

# Bullets for a commit range, filtered to user-facing conventional-commit types.
# $1 = a git revision range (e.g. "v0.0.1..HEAD") or a single ref. Emits
# "- <subject>" lines, or "- Initial release" when the range has no such commit.
bullets() {
	subjects="$(git log --no-merges --format='%s' "$1" 2>/dev/null \
		| grep -E '^(feat|fix|perf)(\(.+\))?!?:' || true)"
	if [ -n "$subjects" ]; then
		printf '%s\n' "$subjects" | sed 's/^/- /'
	else
		printf -- '- Initial release\n'
	fi
}

# Entry header line. $1 = ref (for date/author), $2 = "version-release" label.
# Prefers an annotated tag's tagger identity, else the commit author.
header() {
	d="$(git log -1 --date='format:%a %b %d %Y' --format='%cd' "$1")"
	who="$(git for-each-ref --format='%(taggername) %(taggeremail)' "refs/tags/$1" 2>/dev/null || true)"
	case "$who" in
		*@*) : ;;
		*) who="$(git log -1 --format='%an <%ae>' "$1")" ;;
	esac
	printf '* %s %s - %s\n' "$d" "$who" "$2"
}

printf '%%changelog\n'

tags="$(git tag --list 'v*' --sort=-version:refname)"
newest="$(printf '%s\n' "$tags" | head -n1)"

# Untagged/snapshot build: HEAD is past the newest release tag, so lead with an
# entry for the version actually being built.
if [ "$newest" != "v${build_version}" ]; then
	header HEAD "${build_version}-1"
	if [ -n "$newest" ]; then bullets "${newest}..HEAD"; else bullets HEAD; fi
	printf '\n'
fi

# One entry per release tag, newest first; each range is bounded below by the
# next-older tag (the oldest tag's range is its whole ancestry).
set -- $tags
while [ "$#" -gt 0 ]; do
	tag="$1"
	shift
	older="${1:-}"
	header "$tag" "${tag#v}-1"
	if [ -n "$older" ]; then bullets "${older}..${tag}"; else bullets "$tag"; fi
	printf '\n'
done
