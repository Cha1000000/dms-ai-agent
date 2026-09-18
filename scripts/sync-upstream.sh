#!/usr/bin/env bash
# Merge the original plugin (Francisdelca/dms-agent) into this fork.
#
#   scripts/sync-upstream.sh        local: merge; on conflict leave it in the
#                                   working tree for you to resolve
#   scripts/sync-upstream.sh --ci   GitHub Actions: merge and push when clean,
#                                   otherwise abort and open an issue
#
# Why merge and not rebase: installed copies update with `git pull` (that is
# what DMS runs). A merge keeps the fork's history append-only, so every pull
# is a fast-forward; a rebase would rewrite it and DMS would fall back to
# deleting and re-cloning the plugin.

set -euo pipefail

UPSTREAM_URL="https://github.com/Francisdelca/dms-agent"
UPSTREAM_BRANCH="main"
CI=0
[ "${1:-}" = "--ci" ] && CI=1

cd "$(git rev-parse --show-toplevel)"

git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
git fetch --quiet upstream "$UPSTREAM_BRANCH"

# Files the fork owns entirely (see .gitattributes, merge=ours).
git config merge.ours.driver true
# Remember conflict resolutions: the same hunk conflicting again resolves itself.
git config rerere.enabled true
git config rerere.autoupdate true

if git merge-base --is-ancestor "upstream/$UPSTREAM_BRANCH" HEAD; then
    echo "Already up to date with upstream."
    exit 0
fi

new_commits="$(git log --oneline "HEAD..upstream/$UPSTREAM_BRANCH")"
echo "Upstream commits to merge:"
echo "$new_commits"

if git merge --no-ff --no-edit -m "Merge upstream $(git rev-parse --short "upstream/$UPSTREAM_BRANCH") into fork" "upstream/$UPSTREAM_BRANCH"; then
    # Cheap sanity checks: a broken merge should not reach users.
    for f in *.py; do python3 -m py_compile "$f"; done
    for f in *.sh scripts/*.sh; do bash -n "$f"; done
    echo "Merged cleanly."
    if [ "$CI" = 1 ]; then
        git push origin HEAD
    else
        echo "Review, then push: git push origin HEAD"
    fi
    exit 0
fi

conflicts="$(git diff --name-only --diff-filter=U)"
if [ "$CI" = 0 ]; then
    cat <<EOF

Merge conflict in:
$conflicts

Resolve each file (keep upstream's fix when it covers ours, keep ours for
fork-only features), then:  git add <files> && git commit && git push origin HEAD
To give up:                 git merge --abort
EOF
    exit 1
fi

git merge --abort
title="Upstream sync: merge conflict"
body="$(cat <<EOF
The daily sync could not merge \`upstream/$UPSTREAM_BRANCH\` automatically.

**Conflicting files**
$(printf '%s\n' "$conflicts" | sed 's/^/- `/; s/$/`/')

**New upstream commits**
\`\`\`
$new_commits
\`\`\`

**How to resolve** (locally, in the plugin checkout):
\`\`\`
scripts/sync-upstream.sh      # leaves the conflict in the working tree
# fix the files, then
git add <files> && git commit && git push origin HEAD
\`\`\`
Rule of thumb: when upstream now contains the same fix, take theirs; keep ours
for fork-only features. This issue closes itself after the next clean sync.
EOF
)"
existing="$(gh issue list --state open --search "\"$title\" in:title" --json number --jq '.[0].number' || true)"
if [ -n "$existing" ]; then
    gh issue comment "$existing" --body "$body"
else
    gh issue create --title "$title" --body "$body"
fi
exit 1
