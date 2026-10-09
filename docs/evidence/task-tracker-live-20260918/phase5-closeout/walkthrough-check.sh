# Evidence check only: pass a repository revision, run from that repository.
# Added after review; this is not represented as a pre-change committed test.
set -eu
reviewed_revision="$1"
git cat-file -e "${reviewed_revision}:docs/evidence/task-tracker-live-20260918/REPRODUCE.md"
