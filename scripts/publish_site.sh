#!/bin/sh
# Publish the same manifest-driven output produced by nwb release.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
if [ "$#" -ne 1 ]; then
    echo "usage: scripts/publish_site.sh RELEASE_MANIFEST.toml" >&2
    exit 2
fi
manifest=$1
origin=$(git remote get-url origin)
author_name=$(git var GIT_AUTHOR_IDENT | sed 's/ <.*//')
author_email=$(git var GIT_AUTHOR_IDENT | sed 's/.*<\(.*\)>.*/\1/')
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

uv run nwb release --manifest "$manifest" --out "$tmp"
git -C "$tmp" init -q -b gh-pages
git -C "$tmp" add .
git -C "$tmp" -c user.name="$author_name" -c user.email="$author_email" \
    commit -q -m "Publish benchmark results ($manifest)"
git -C "$tmp" push --force "$origin" gh-pages
