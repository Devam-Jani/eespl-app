# ruff: noqa: E501
"""The nightly backup, its retention, the off-site copy and the restore (the `backup` container;
standard library only, so it runs on the postgres image with python3, gpg and rclone).

    python3 backup.py loop                 # wait for BACKUP_HOUR, back up, repeat (the service)
    python3 backup.py run                  # one backup now
    python3 backup.py prune [--dry-run]    # apply the retention
    python3 backup.py restore ARCHIVE --into DBNAME [--media DIR] [--drop]
    python3 backup.py counts [DBNAME]      # row counts of every table (to compare a restore)
    python3 backup.py check                # the container's health check

An archive is one file, eespl-YYYYMMDD-HHMM.tar.gpg: a tar of the database (pg_dump, custom
format), the media volume (photos, drawings, PDFs) and a manifest with each table's row count,
encrypted (AES-256, gpg symmetric) with BACKUP_KEY from .env. Kept: the newest BACKUP_KEEP_DAILY
days, the newest archive of each of the last BACKUP_KEEP_WEEKLY weeks and of each of the last
BACKUP_KEEP_MONTHLY months; the rest are removed. BACKUP_REMOTE (an rclone remote, e.g.
"offsite:eespl-backups", configured with RCLONE_CONFIG_* in .env; any S3-compatible bucket or a
folder) gets the same set; off until set. The result goes into system_status (key "backup") for the
admin page and the missed-backup alert. Secrets are never printed."""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

NAME = re.compile(r"^eespl-(\d{8})-(\d{4})\.tar\.gpg$")
ALIVE = Path("/tmp/backup-alive")


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def backup_dir() -> Path:
    return Path(env("BACKUP_DIR", "/backups"))


# --- retention -----------------------------------------------------------------------------------


def archive_date(name: str) -> datetime | None:
    m = NAME.match(name)
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M") if m else None


def plan(names: list[str], daily: int = 14, weekly: int = 8, monthly: int = 12) -> tuple[list[str], list[str]]:
    """(keep, remove): the newest archive of each of the last `daily` days, of each of the last
    `weekly` ISO weeks and of each of the last `monthly` months (counted from the newest archive,
    so a server that was off keeps what it has). Names that are not archives are left alone."""
    dated = sorted(((archive_date(n), n) for n in names if archive_date(n)), reverse=True)
    if not dated:
        return [], []
    newest = dated[0][0].date()
    keep: set[str] = set()

    def newest_per(key, limit: int, in_range) -> None:
        seen: set = set()
        for d, n in dated:  # newest first: the first of each key is its newest archive
            k = key(d.date())
            if k in seen or not in_range(d.date()):
                continue
            seen.add(k)
            keep.add(n)

    newest_per(lambda d: d, daily, lambda d: (newest - d).days < daily)
    first_week = newest - timedelta(days=newest.weekday()) - timedelta(weeks=weekly - 1)
    newest_per(lambda d: d.isocalendar()[:2], weekly, lambda d: d >= first_week)
    y, m = newest.year, newest.month - (monthly - 1)
    while m <= 0:
        y, m = y - 1, m + 12
    first_month = date(y, m, 1)
    newest_per(lambda d: (d.year, d.month), monthly, lambda d: d >= first_month)
    archives = [n for _d, n in dated]
    return [n for n in archives if n in keep], [n for n in archives if n not in keep]


# --- the backup ------------------------------------------------------------------------------------


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def counts(dbname: str | None = None) -> dict[str, int]:
    """Every table's row count (exact), for the manifest and for comparing a restore."""
    db = dbname or env("PGDATABASE")
    tables = _run(["psql", "-d", db, "-At", "-c", "SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"],
                  capture_output=True, text=True).stdout.split()  # fmt: skip
    if not tables:
        return {}
    sql = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM {t}" for t in tables)
    out = _run(["psql", "-d", db, "-At", "-F", "\t", "-c", sql], capture_output=True, text=True).stdout
    return {line.split("\t")[0].removeprefix("public."): int(line.split("\t")[1]) for line in out.splitlines() if line}


def _key_file(tmp: Path) -> Path:
    key = env("BACKUP_KEY")
    if len(key) < 24:
        raise SystemExit("BACKUP_KEY is missing or too short (set it in .env with scripts/make-prod-secrets.py)")
    f = tmp / "key"
    f.write_text(key)
    f.chmod(0o600)
    return f


def run(now: datetime | None = None) -> dict:
    """One backup: dump, media, manifest, encrypt into the backup folder; prune; copy off-site."""
    now = now or datetime.now()
    name = f"eespl-{now:%Y%m%d-%H%M}.tar.gpg"
    out = backup_dir() / name
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        work = tmp / "work"
        work.mkdir()
        _run(["pg_dump", "-Fc", "--no-owner", "-f", str(work / "db.dump")])
        media = Path(env("MEDIA_DIR", "/media"))
        _run(["tar", "-cf", str(work / "media.tar"), "-C", str(media), "."] if media.exists() else ["tar", "-cf", str(work / "media.tar"), "-T", "/dev/null"])
        manifest = {"made": now.isoformat(), "database": env("PGDATABASE"), "counts": counts(), "media_bytes": (work / "media.tar").stat().st_size}
        (work / "manifest.json").write_text(json.dumps(manifest, indent=1))
        key = _key_file(tmp)
        tar = subprocess.Popen(["tar", "-cf", "-", "-C", str(work), "manifest.json", "db.dump", "media.tar"], stdout=subprocess.PIPE)
        _run(["gpg", "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback", "--passphrase-file", str(key), "--symmetric", "--cipher-algo", "AES256",
              "--compress-algo", "zlib", "-o", str(out)], stdin=tar.stdout)  # fmt: skip
        tar.stdout.close()
        if tar.wait() != 0:
            raise RuntimeError("tar failed")
    kept, removed = prune()
    offsite = copy_offsite()
    return {"ok": True, "archive": name, "bytes": out.stat().st_size, "tables": len(manifest["counts"]), "rows": sum(manifest["counts"].values()),
            "kept": len(kept), "removed": removed, "offsite": offsite}  # fmt: skip


def prune(dry_run: bool = False) -> tuple[list[str], list[str]]:
    names = [p.name for p in backup_dir().glob("eespl-*.tar.gpg")]
    keep, remove = plan(names, int(env("BACKUP_KEEP_DAILY", "14")), int(env("BACKUP_KEEP_WEEKLY", "8")), int(env("BACKUP_KEEP_MONTHLY", "12")))
    if not dry_run:
        for n in remove:
            (backup_dir() / n).unlink(missing_ok=True)
    return keep, remove


def copy_offsite() -> str | None:
    """The kept archives to BACKUP_REMOTE (rclone sync: deletions follow the retention)."""
    remote = env("BACKUP_REMOTE")
    if not remote:
        return None
    _run(["rclone", "sync", str(backup_dir()), remote, "--include", "eespl-*.tar.gpg", "--quiet"])
    return remote.split(":", 1)[0] + ":…"  # the remote's name, never its keys


def write_status(result: dict) -> None:
    value = json.dumps(result).replace("'", "''")
    sql = f"INSERT INTO system_status (key, value, at) VALUES ('backup', '{value}', now()) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, at = EXCLUDED.at"
    subprocess.run(["psql", "-At", "-c", sql], check=False, capture_output=True)


def run_and_report() -> dict:
    try:
        result = run()
    except Exception as exc:  # noqa: BLE001  the alert says what failed (never a secret)
        result = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    write_status(result)
    if result.get("ok"):
        print(f"backup {result['archive']}: {result['bytes']} bytes, {result['tables']} tables, kept {result['kept']}, removed {len(result['removed'])}", flush=True)
    else:
        print(f"backup failed: {result['error']}", flush=True)
    return result


def loop() -> None:
    hour = int(env("BACKUP_HOUR", "2"))
    while True:
        now = datetime.now()
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        while datetime.now() < nxt:
            ALIVE.write_text(datetime.now(UTC).isoformat())
            time.sleep(min(300, max(1, (nxt - datetime.now()).total_seconds())))
        run_and_report()


# --- the restore ---------------------------------------------------------------------------------------


def restore(archive: str, into: str, media_dir: str | None = None, drop: bool = False) -> dict:
    """The archive into a fresh database `into` (made here; --drop replaces one that exists), and
    the media into media_dir when given. Returns the manifest's counts and the restored ones."""
    path = Path(archive) if "/" in archive else backup_dir() / archive
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        key = _key_file(tmp)
        dec = subprocess.Popen(["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase-file", str(key), "--decrypt", str(path)], stdout=subprocess.PIPE)
        _run(["tar", "-xf", "-", "-C", str(tmp)], stdin=dec.stdout)
        dec.stdout.close()
        if dec.wait() != 0:
            raise SystemExit("Could not decrypt the archive (wrong BACKUP_KEY?)")
        manifest = json.loads((tmp / "manifest.json").read_text())
        exists = _run(["psql", "-d", "postgres", "-At", "-c", f"SELECT 1 FROM pg_database WHERE datname = '{into}'"], capture_output=True, text=True).stdout.strip()
        if exists and not drop:
            raise SystemExit(f"Database {into} exists: restore into a fresh one, or pass --drop")
        if exists:
            _run(["dropdb", "--force", into])
        _run(["createdb", into])
        _run(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "-d", into, str(tmp / "db.dump")])
        if media_dir:
            Path(media_dir).mkdir(parents=True, exist_ok=True)
            _run(["tar", "-xf", str(tmp / "media.tar"), "-C", media_dir])
    got = counts(into)
    diff = {t: (manifest["counts"].get(t), got.get(t)) for t in set(manifest["counts"]) | set(got) if manifest["counts"].get(t) != got.get(t)}
    archived = manifest["counts"]
    largest = sorted(archived, key=lambda t: -archived[t])[:8]
    return {"archive": path.name, "into": into, "archived_tables": len(archived), "archived_rows": sum(archived.values()),
            "tables": len(got), "rows": sum(got.values()), "largest": {t: [archived[t], got.get(t)] for t in largest}, "differences": diff}


def check() -> int:
    """Healthy while the loop is waiting (it touches a file every five minutes)."""
    try:
        seen = datetime.fromisoformat(ALIVE.read_text())
    except (OSError, ValueError):
        return 1
    return 0 if datetime.now(UTC) - seen < timedelta(minutes=12) else 1


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "run"
    if cmd == "loop":
        loop()
    elif cmd == "run":
        return 0 if run_and_report().get("ok") else 1
    elif cmd == "prune":
        keep, remove = prune(dry_run="--dry-run" in argv)
        print(json.dumps({"keep": keep, "remove": remove}, indent=1))
    elif cmd == "restore":
        into = argv[argv.index("--into") + 1]
        media = argv[argv.index("--media") + 1] if "--media" in argv else None
        print(json.dumps(restore(argv[1], into, media, "--drop" in argv), indent=1))
    elif cmd == "counts":
        print(json.dumps(counts(argv[1] if len(argv) > 1 else None), indent=1, sort_keys=True))
    elif cmd == "check":
        return check()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
