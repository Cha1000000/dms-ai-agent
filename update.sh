#!/usr/bin/env bash
# Pull plugin updates from the repository it was cloned from.
#
# Prints one word for the caller to act on:
#   updated   commits were pulled
#   uptodate  already current
#   dirty     the working copy has local edits — left alone
#   diverged  local commits, a fast-forward is not possible — left alone
#   offline   git fetch did not succeed
#   notgit    not a git clone (installed some other way)
#
# Only ever fast-forwards. A plugin that resets somebody's working copy to
# match a remote will eventually throw away work that mattered.
set -uo pipefail

cd "$(dirname "$(readlink -f "$0")")" || exit 1

[ -d .git ] || { echo notgit; exit 0; }

# Anything uncommitted means someone is working in here.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo dirty
    exit 0
fi

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

if [ "$local_head" = "$remote_head" ]; then
    echo uptodate
    exit 0
fi

# Behind is fine; anything else means local history of its own.
if ! git merge-base --is-ancestor HEAD "origin/$branch" 2>/dev/null; then
    echo diverged
    exit 0
fi

if git merge --ff-only --quiet "origin/$branch" 2>/dev/null; then
    echo updated
else
    echo diverged
fi
