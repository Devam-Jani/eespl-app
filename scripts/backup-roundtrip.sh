#!/usr/bin/env sh
# The backup round trip on the development PC, against the local production run (ENV_FILE and
# --env-file .env.prod.local): the development database (with its DEMO data) and media are backed
# up by the production backup container exactly as at night, restored into a fresh database, and
# every table's rows and the media files are compared. Nothing touches the development stack
# except reading it; no secret is printed.
#
#   ENV_FILE=.env.prod.local sh scripts/backup-roundtrip.sh
set -eu
cd "$(dirname "$0")/.."
ENV_FILE="${ENV_FILE:-.env.prod.local}"
export ENV_FILE
PROD="docker compose -p eespl-prod -f docker-compose.prod.yml --env-file $ENV_FILE"
DEV="docker compose"

echo "== 1. the development database copied into the production server's db (eespl_devcopy)"
$PROD exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists eespl_devcopy; dropdb -U "$POSTGRES_USER" --if-exists eespl_roundtrip; createdb -U "$POSTGRES_USER" eespl_devcopy'
$DEV exec -T db pg_dump -U eespl -Fc eespl | $PROD exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d eespl_devcopy --no-owner --no-privileges'

echo "== 2. backup (pg_dump -Fc + media, encrypted), restore into eespl_roundtrip, compare"
MSYS_NO_PATHCONV=1 $PROD run --rm --no-deps -v eespl_media:/devmedia:ro \
  -e PGDATABASE=eespl_devcopy -e MEDIA_DIR=/devmedia -e BACKUP_DIR=/backups/roundtrip \
  --entrypoint sh backup -c '
set -e
python3 /opt/backup/backup.py run
a=$(ls -t /backups/roundtrip | grep "^eespl-" | head -1)
echo "archive: $a ($(du -h /backups/roundtrip/$a | cut -f1))"
python3 /opt/backup/backup.py restore "$a" --into eespl_roundtrip --media /tmp/restored > /tmp/result.json
python3 - <<EOF
import json
r = json.load(open("/tmp/result.json"))
print("tables: %d in the archive, %d restored" % (r["archived_tables"], r["tables"]))
print("rows:   %d in the archive, %d restored" % (r["archived_rows"], r["rows"]))
for t, (a, b) in r["largest"].items():
    print(f"   {t:36} {a:>8} -> {b}")
print("differences:", r["differences"] or "none")
EOF
m1=$(find /devmedia -type f | wc -l); m2=$(find /tmp/restored -type f | wc -l)
echo "media files: $m1 backed up, $m2 restored"
[ "$m1" = "$m2" ]
'
$PROD exec -T db sh -c 'dropdb -U "$POSTGRES_USER" eespl_devcopy; dropdb -U "$POSTGRES_USER" eespl_roundtrip'
echo "== round trip complete"
