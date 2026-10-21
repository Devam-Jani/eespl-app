#!/usr/bin/env sh
# Test the newest migration both ways on the dev database: down one step, up again.
# Every step must succeed before the next one runs (set -e and &&): a failed upgrade must
# never be followed by a downgrade, which once dropped a table's rows on the dev database.
# Never pipe a step through `tail`/`head` inside the chain: the pipe returns the tail's exit
# code and hides the failure.
#
#   sh scripts/migration-roundtrip.sh          # from the repository root
set -eu

run() {
  docker compose exec -T -w /app api alembic "$@"
}

run upgrade head
before=$(run current | tail -n 1)
echo "current: $before"
run downgrade -1
run upgrade head
after=$(run current | tail -n 1)
echo "current: $after"
[ "$before" = "$after" ] || { echo "the head moved: $before -> $after" >&2; exit 1; }
echo "round trip ok"
