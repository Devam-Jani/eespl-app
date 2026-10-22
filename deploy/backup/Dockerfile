# The nightly backup: pg_dump of the same major version as the server (postgres:16), gpg for the
# encryption and rclone for the off-site copy. Build context: ./backend (the script is
# app/ops/backup.py, standard library only).
FROM postgres:16

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 gnupg rclone ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Kolkata BACKUP_DIR=/backups MEDIA_DIR=/media
COPY app/ops/backup.py /opt/backup/backup.py
VOLUME ["/backups"]
CMD ["python3", "/opt/backup/backup.py", "loop"]
