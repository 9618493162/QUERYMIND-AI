# Change detection gate — exactly what the CI workflow runs for live-required.
# Intentional: portable Bash, testable against real git histories.

set -euo pipefail

# GitHub sets this for Actions jobs; local callers can also set it.
REPO_ROOT="${GIT_WORK_TREE:-}"
if [[ -z "$REPO_ROOT" ]]; then
    if REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
        :
    else
        REPO_ROOT="/"
    fi
fi

BASE_REF="${1:-}"
EVENT="${2:-$GITHUB_EVENT_NAME}"
# wf_live == 'true' | 'false' | unset
WF_LIVE="${3:-$GITHUB_WORKFLOW_LIVE}"

is_true() {
    case "${1:-}" in
    true | 1 | [Tt]rue) return 0 ;;
    *) return 1 ;;
    esac
}

is_false() {
    case "${1:-}" in
    false | 0 | [Ff]alse | '') return 0 ;;
    *) return 1 ;;
    esac
}

detect_changes_between_branches() {
    local before="$1"
    local after="${2:-HEAD}"

    if ! git rev-parse --verify --quiet "$before" >/dev/null 2>&1; then
        echo "true" # base branch doesn't exist — treat as changed
        return 0
    fi

    local changed=false
    # Paths relevant to live verification.
    if git diff --quiet "$before" "$after" -- \
        .github/workflows/ci.yml \
        .github/scripts/detect-live-required.sh \
        backend/scripts/live_e2e_check.py \
        backend/scripts/live_failure_check.py \
        backend/app/tests/test_read_only_enforcement.py \
        backend/app/tests/test_llm_integration.py \
        backend/alembic/*.py \
        backend/alembic/versions/*.py \
        backend/app/services/ai_service.py \
        backend/app/services/query_executor.py \
        backend/app/services/sql_validator.py \
        backend/app/services/schema_visualizer.py \
        backend/app/services/connection_service.py \
        backend/app/services/schema_service.py \
        backend/app/services/query_parser.py \
        backend/app/services/sql_parser.py \
        backend/app/api/query.py \
        backend/app/api/connections.py \
        backend/requirements.txt \
        backend/pytest.ini \
        backend/app/config.py \
        Dockerfile \
        docker-compose.override.yml \
        docker-compose.yml \
        docker/.env.example \
        docker/.env.ollama \
        docker/ollama/Dockerfile \
        ollama/prompts/ \
        prompts/ \
        docker-compose.override.yml 2>/dev/null; then
        :
    else
        changed=true
    fi

    # Any changed file is also a signal for subscription events.
    if ! git diff --quiet "$before" "$after" 2>/dev/null; then
        changed=true
    fi

    if $changed; then
        echo "true"
    else
        echo "false"
    fi
}

if is_false "$WF_LIVE"; then
    echo "false"
    exit 0
fi

case "$EVENT" in
push)
    if is_true "$BASE_REF"; then
        echo "true"
    else
        # Diff against the previous commit on the same branch.
        if ! git rev-parse --verify --quiet "HEAD~1" >/dev/null 2>&1; then
            echo "true" # single commit
        else
            detect_changes_between_branches "HEAD~1"
        fi
    fi
    ;;
pull_request)
    # GitHub Actions sets GITHUB_BASE_REF for PRs targeting the same repo,
    # and the merge ref contains the actual comparison set.
    if git rev-parse --verify --quiet "refs/pull/$GITHUB_PR_NUMBER/merge" >/dev/null 2>&1; then
        detect_changes_between_branches "origin/$GITHUB_BASE_REF" "refs/pull/$GITHUB_PR_NUMBER/merge"
    elif git rev-parse --verify --quiet "origin/$BASE_REF" >/dev/null 2>&1; then
        detect_changes_between_branches "origin/$BASE_REF" "HEAD"
    else
        echo "true"
    fi
    ;;
workflow_dispatch)
    if is_true "$BASE_REF"; then
        echo "true"
    else
        if ! git rev-parse --verify --quiet "HEAD~1" >/dev/null 2>&1; then
            echo "true"
        else
            detect_changes_between_branches "HEAD~1"
        fi
    fi
    ;;
*)
    echo "true"
    ;;
esac
