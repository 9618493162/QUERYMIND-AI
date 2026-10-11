#!/usr/bin/env bash
# Decide whether the expensive live checks (real model + real database) must run
# for the current change.
#
#   live=true   -> the change touches AI, SQL, database, security, API, scripts or CI
#   live=false  -> documentation-only or otherwise unrelated change
#
# Unknown or uncomparable diffs are treated as live=true on purpose: it is safer
# to spend a model run than to let a risky change merge without live verification.
#
# Inputs (environment, all optional — every read is ${VAR:-} so `set -u` is safe):
#   EVENT      pull_request | push | workflow_dispatch | other
#   REQUESTED  workflow_dispatch input: auto | always | never
#   BASE_REF   pull request base branch (e.g. main)
#   BEFORE     push event "before" SHA
#   SHA        the commit being built (defaults to HEAD)
#   GITHUB_OUTPUT  when set, `live=<bool>` is appended for the workflow step output
#
# Output: a `live=<bool>` line on stdout (reasons on stderr) and, when
# GITHUB_OUTPUT is provided, the same line appended to that file.

set -euo pipefail

EVENT="${EVENT:-${GITHUB_EVENT_NAME:-other}}"
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
    echo "reason: $reason" >&2
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "live=$value" >>"$GITHUB_OUTPUT"
    fi
}

decide_from_range() {
    local range="$1" reason="$2"
    local changed
    if ! changed="$(git diff --name-only "$range" 2>/dev/null)" || [ -z "$changed" ]; then
        emit true "no comparable diff for $range ($reason)"
        return 0
    fi
    if echo "$changed" | grep -Eq "$LIVE_PATTERN"; then
        emit true "live-relevant paths changed ($reason)"
    else
        emit false "only unrelated paths changed ($reason)"
    fi
}

case "$REQUESTED" in
always)
    emit true "forced by workflow_dispatch input"
    exit 0
    ;;
never)
    emit false "disabled by workflow_dispatch input"
    exit 0
    ;;
esac

case "$EVENT" in
pull_request)
    if git rev-parse --verify --quiet "origin/${BASE_REF}" >/dev/null; then
        decide_from_range "origin/${BASE_REF}...HEAD" "pull request against ${BASE_REF}"
    else
        # Without the base branch the diff cannot be trusted; be conservative.
        emit true "base branch origin/${BASE_REF} unavailable to compare against"
    fi
    ;;
push)
    # A first push (empty/absent before-SHA) or force push cannot be diffed
    # reliably — a HEAD~1 comparison would hide the rest of the pushed history.
    if [ -z "$BEFORE" ] || [ "$BEFORE" = "0000000000000000000000000000000000000000" ]; then
        emit true "first push or unknown before-SHA on push event"
    elif ! git cat-file -e "$BEFORE" 2>/dev/null; then
        emit true "before-SHA $BEFORE not present locally (force push?)"
    else
        decide_from_range "${BEFORE}..${SHA}" "push event"
    fi
    ;;
*)
    # workflow_dispatch and unknown events: gate on the latest commit so an
    # explicit run with live=auto still spends the model only when needed.
    if git rev-parse --verify --quiet "${SHA}~1" >/dev/null; then
        decide_from_range "${SHA}~1..${SHA}" "event '$EVENT'"
    else
        emit true "single-commit history for event '$EVENT'"
    fi
    ;;
esac
