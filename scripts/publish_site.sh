#!/bin/sh
# Publish only generated results, without switching the repository's branch.
# The core suite goes to the site root and naihub-v1 to naihub-v1/, linked by suite tabs.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
core_run=${1:-v1}
naihub_run=${2:-naihub-v1}
origin=$(git remote get-url origin)
author_name=$(git var GIT_AUTHOR_IDENT | sed 's/ <.*//')
author_email=$(git var GIT_AUTHOR_IDENT | sed 's/.*<\(.*\)>.*/\1/')
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

uv run nwb site --run "$core_run" --out "$tmp" --suite-tabs \
    --repo-url https://github.com/wusitee/nai-wai-bench
uv run nwb site --suite naihub-v1 --run "$naihub_run" --out "$tmp/naihub-v1" --suite-tabs \
    --repo-url https://github.com/wusitee/nai-wai-bench
touch "$tmp/.nojekyll"
git -C "$tmp" init -q -b gh-pages
git -C "$tmp" add .
git -C "$tmp" -c user.name="$author_name" -c user.email="$author_email" \
    commit -q -m "Publish benchmark results ($core_run, $naihub_run)"
git -C "$tmp" push --force "$origin" gh-pages
