#!/usr/bin/env bash
# GitHub-only origin lookup; the Python policy itself is offline and DB-free.
set -euo pipefail
: "${GITHUB_REPOSITORY:?repository is required}"
: "${GITHUB_RUN_ID:?run ID is required}"
: "${GITHUB_OUTPUT:?output file is required}"
created_at="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}" --jq .created_at)"
if session_date="$(python -m src.collection_session --run-created-at "$created_at")"; then
  echo 'eligible=true' >> "$GITHUB_OUTPUT"
  echo "session_date=$session_date" >> "$GITHUB_OUTPUT"
  echo "Collection session: $session_date"
else
  code=$?
  if [ "$code" -eq 3 ]; then
    echo 'eligible=false' >> "$GITHUB_OUTPUT"
    echo 'No exchange session: skipping collection and publication'
  else
    echo 'Session preflight failed; collection and publication refused' >&2
    exit "$code"
  fi
fi
