#!/usr/bin/env bash
# Tell whether the repository this plugin was cloned from has newer commits.
# Only looks: nothing is merged, reset or restarted — updating is DMS's job
# (Settings → Plugins → Update).
#
# Prints one word for the caller to act on:
#   available  the remote has commits this copy does not
#   uptodate   nothing new (or this copy is ahead)
#   offline    git fetch did not succeed
#   notgit     not a git clone (installed some other way)
set -uo pipefail

cd "$(dirname "$(readlink -f "$0")")" || exit 1

[ -d .git ] || { echo notgit; exit 0; }

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
[ -n "$branch" ] && [ "$branch" != "HEAD" ] || { echo notgit; exit 0; }

# A network that merely hangs must not hold the shell's startup.
if ! timeout 25 git fetch --quiet origin "$branch" 2>/dev/null; then
    echo offline
    exit 0
fi

local_head=$(git rev-parse HEAD 2>/dev/null)
remote_head=$(git rev-parse "origin/$branch" 2>/dev/null)
[ -n "$remote_head" ] || { echo offline; exit 0; }

if [ "$local_head" != "$remote_head" ] && git merge-base --is-ancestor HEAD "origin/$branch" 2>/dev/null; then
    echo available
else
    echo uptodate
fi
