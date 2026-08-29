#!/usr/bin/env bash
# One pass of the Codex-NPB daily cycle, safe to run unattended.
#
# Settles any board that was priced but never graded, refreshes the season
# data, builds the next slate, prices it if a board is already present, then
# commits and pushes. Every step is echoed so a scheduled run leaves a
# readable trail, and any failure stops the script rather than pushing a
# half-finished state.

set -euo pipefail

BRANCH="${NPB_BRANCH:-claude/repository-sync-66695m}"
DELAY="${NPB_DELAY:-0.4}"

find_repo() {
    for candidate in /home/user/Codex-NPB "$HOME/Codex-NPB" "$(pwd)"; do
        [ -f "$candidate/pyproject.toml" ] && { echo "$candidate"; return 0; }
    done
    find / -maxdepth 5 -name pyproject.toml -path '*Codex-NPB*' \
        -not -path '*/node_modules/*' 2>/dev/null | head -1 | xargs -r dirname
}

REPO="$(find_repo)"
if [ -z "$REPO" ] || [ ! -f "$REPO/pyproject.toml" ]; then
    echo "FATAL: could not locate the Codex-NPB checkout." >&2
    echo "Searched /home/user/Codex-NPB, \$HOME/Codex-NPB and \$(pwd)." >&2
    echo "Current directory is $(pwd), which contains:" >&2
    ls -la >&2
    exit 1
fi
cd "$REPO"
echo "repo: $REPO"

echo "=== syncing $BRANCH ==="
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
git log --format='at %h %s' -1

echo
echo "=== daily cycle ==="
PYTHONPATH=src python3 -c \
    "from codex_npb.pipeline_cli import daily_main; daily_main(['--delay','$DELAY'])"

echo
echo "=== cumulative record ==="
PYTHONPATH=src python3 -c \
    "from codex_npb.pipeline_cli import record_main; record_main([])" || true

echo
if [ -z "$(git status --porcelain)" ]; then
    echo "=== nothing changed; no commit ==="
    exit 0
fi
echo "=== committing ==="
git add -A
git commit -q -m "Daily cycle $(date -u +%Y-%m-%d): settle and prepare

Automated run of scripts/daily_cycle.sh."
for attempt in 1 2 3 4; do
    if git push -u origin "$BRANCH"; then
        echo "pushed"
        exit 0
    fi
    echo "push failed, retry $attempt"
    sleep $((2 ** attempt))
done
echo "FATAL: push failed after 4 attempts" >&2
exit 1
