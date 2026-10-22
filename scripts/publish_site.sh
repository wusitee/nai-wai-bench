#!/bin/sh
# Publish only generated results, without switching the repository's branch.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
origin=$(git remote get-url origin)
author_name=$(git var GIT_AUTHOR_IDENT | sed 's/ <.*//')
author_email=$(git var GIT_AUTHOR_IDENT | sed 's/.*<\(.*\)>.*/\1/')
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

uv run nwb site --run "${1:-v1}" --out "$tmp" \
    --repo-url https://github.com/wusitee/nai-wai-bench
touch "$tmp/.nojekyll"
git -C "$tmp" init -q -b gh-pages
git -C "$tmp" add .
git -C "$tmp" -c user.name="$author_name" -c user.email="$author_email" \
    commit -q -m "Publish benchmark results (${1:-v1})"
git -C "$tmp" push --force "$origin" gh-pages
