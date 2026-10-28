#!/usr/bin/env sh
# Restore a backup archive into a fresh database (and the media into a folder), on the server:
#
#   sh scripts/restore.sh                                    # list the archives
#   sh scripts/restore.sh eespl-20261101-0200.tar.gpg eespl_restored
#
# It runs in the backup container (pg_restore of the server's version, the BACKUP_KEY from .env).
# Restoring over the live database (and its media) is docs/DEPLOY.md section 10, not this script.
# Prints the restored tables and rows, and any table whose count differs from the archive's
# manifest (none means the restore is complete). No secret is printed.
# Behind an existing nginx (the test server): COMPOSE="docker compose -p eespl-test -f
# docker-compose.prod.yml -f docker-compose.behind-proxy.yml" sh scripts/restore.sh ...
set -eu
COMPOSE="${COMPOSE:-docker compose -f docker-compose.prod.yml}"

if [ $# -lt 2 ]; then
  echo "Archives in the backups volume:"
  $COMPOSE exec -T backup sh -c 'ls -lh /backups | grep eespl- || echo "(none yet)"'
  echo "Usage: sh scripts/restore.sh ARCHIVE NEW_DATABASE [--drop] [--media DIR]"
  exit 1
fi

archive="$1"
into="$2"
shift 2
$COMPOSE exec -T backup python3 /opt/backup/backup.py restore "$archive" --into "$into" "$@"
