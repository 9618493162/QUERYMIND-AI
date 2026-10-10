#!/usr/bin/env bash
# Decide whether the expensive live checks (real model + real database) must run
# for the current change.
#
#   live=true   -> the change touches AI, SQL, database, security, API, scripts or CI
#   live=false  -> documentation-only or otherwise unrelated change
#
# Unknown diffs are treated as "live=true" on purpose: it is safer to spend a
# model run than to let a risky change merge without live verification.
#
# Inputs (environment):
#   EVENT      pull_request | push | workflow_dispatch | other
#   REQUESTED  workflow_dispatch input: auto | always | never
#   BASE_REF   pull request base branch (e.g. main)
#   BEFORE     push event "before" SHA
#   SHA        the commit being built (defaults to HEAD)
#
# Output: `live=<bool>` line, echoed to stdout and appended to $GITHUB_OUTPUT
# when that file is provided.

set -euo pipefail

EVENT="${EVENT:-other}"
REQUESTED="${REQUESTED:-auto}"
BASE_REF="${BASE_REF:-}"
BEFORE="${BEFORE:-}"
SHA="${SHA:-HEAD}"

# Paths whose changes can affect real AI inference, SQL generation/validation,
# query execution, database connectivity, authentication, security or the
# verification tooling itself.
LIVE_PATTERN='^(backend/(app|alembic|scripts|requirements\.txt|alembic\.ini|pytest\.ini)|docker-compose\.yml|docker/|\.env\.example|frontend/src/(services|types)/|\.github/)'

emit() {
    local value="$1" reason="$2"
    echo "live=$value"
    echo "reason: $reason"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "live=$value" >> "$GITHUB_OUTPUT"
    fi
}

case "$REQUESTED" in
    always) emit true "forced by workflow_dispatch input"; exit 0 ;;
    never)  emit false "disabled by workflow_dispatch input"; exit 0 ;;
esac

case "$EVENT" in
    pull_request)
        git fetch --no-tags --depth=1 origin "$BASE_REF" >/dev/null 2>&1 || true
        if git rev-parse --verify --quiet "origin/${BASE_REF}" >/dev/null; then
            RANGE="origin/${BASE_REF}...HEAD"
        else
            # Without the base branch the diff cannot be trusted; a PR merge
            # commit's HEAD~1 would hide the real change set, so be conservative.
            emit true "base branch origin/${BASE_REF} unavailable to compare against"
            exit 0
        fi
        ;;
    push)
        if [ -z "$BEFORE" ] || [ "$BEFORE" = "0000000000000000000000000000000000000000" ]; then
            RANGE="HEAD~1..HEAD"
        else
            RANGE="${BEFORE}..${SHA}"
        fi
        ;;
    *)
        emit true "unknown event '$EVENT'"
        exit 0
        ;;
esac

CHANGED="$(git diff --name-only "$RANGE" 2>/dev/null || true)"

if [ -z "$CHANGED" ]; then
    emit true "no comparable diff for $RANGE"
    exit 0
fi

echo "changed files:" >&2
echo "$CHANGED" >&2

if echo "$CHANGED" | grep -Eq "$LIVE_PATTERN"; then
    emit true "live-relevant paths changed"
else
    emit false "only unrelated paths changed"
fi
