"""Make the server's .env from .env.prod.example with fresh secrets.

    python3 scripts/make-prod-secrets.py                    # writes .env (refuses to overwrite)
    python3 scripts/make-prod-secrets.py --out /path/.env --dev-env /path/dev.env
    python3 scripts/make-prod-secrets.py --rotate JWT_SECRET  # a new value for one key in .env

The secrets (JWT_SECRET, POSTGRES_PASSWORD, BACKUP_KEY, DATA_KEY, DEMO_USER_PASSWORD) are made with
the operating system's random source, written only to the output file (mode 600) and never
printed. A value equal to the development .env's (if given or found next to the example) is
refused, so production never reuses the secrets that were shared during development. The other
settings are copied from the example (empty) or the defaults below, to fill in by hand.
Standard library only."""

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = {
    "JWT_SECRET": lambda: secrets.token_urlsafe(48),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(32),
    "BACKUP_KEY": lambda: secrets.token_urlsafe(48),
    "DATA_KEY": lambda: secrets.token_urlsafe(48),
    "DEMO_USER_PASSWORD": lambda: "Train-" + secrets.token_urlsafe(12),
}
DEFAULTS = {
    "POSTGRES_DB": "eespl",
    "POSTGRES_USER": "eespl",
    "TZ": "Asia/Kolkata",
    "TILE_HOST": "tile.openstreetmap.org",
    "BACKUP_HOUR": "2",
    "BACKUP_KEEP_DAILY": "14",
    "BACKUP_KEEP_WEEKLY": "8",
    "BACKUP_KEEP_MONTHLY": "12",
    "EMAIL_ENABLED": "false",
    "SMTP_PORT": "587",
    "KYLAS_ENABLED": "false",
    "KYLAS_BASE_URL": "https://api.kylas.io/v1",
}


def read_env(path: Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def fresh(key: str, avoid: set[str]) -> str:
    for _ in range(10):
        value = SECRETS[key]()
        if value not in avoid:
            return value
    raise SystemExit(f"Could not make a fresh {key}")  # cannot happen with a working random source


def build(example: Path, dev: dict[str, str]) -> str:
    avoid = {v for v in dev.values() if v}
    lines = []
    for line in example.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            value = fresh(key, avoid) if key in SECRETS else DEFAULTS.get(key, "")
            if key in SECRETS and value in avoid:
                raise SystemExit(f"{key} would reuse a development value")
            lines.append(f"{key}={value}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--example", default=str(ROOT / ".env.prod.example"))
    p.add_argument("--out", default=str(ROOT / ".env"))
    p.add_argument("--dev-env", default=None, help="the development .env, whose values must not be reused")
    p.add_argument("--rotate", default=None, help="make a new value for this one secret in --out")
    args = p.parse_args(argv)
    out = Path(args.out)
    dev = read_env(Path(args.dev_env)) if args.dev_env else {}
    if args.rotate:
        if args.rotate not in SECRETS:
            raise SystemExit(f"Only these can be rotated: {', '.join(SECRETS)}")
        cur = read_env(out)
        if not cur:
            raise SystemExit(f"{out} not found")
        avoid = {v for v in dev.values() if v} | {cur.get(args.rotate, "")}
        value = fresh(args.rotate, avoid)
        text = out.read_text(encoding="utf-8")
        lines = [f"{args.rotate}={value}" if ln.startswith(f"{args.rotate}=") else ln for ln in text.splitlines()]
        write_private(out, "\n".join(lines) + "\n")
        print(f"{args.rotate}: rotated in {out} (not shown)")
        return 0
    if out.exists():
        raise SystemExit(f"{out} exists: not overwritten (use --rotate KEY for one secret)")
    write_private(out, build(Path(args.example), dev))
    print(f"Wrote {out} (mode 600). Fresh: {', '.join(SECRETS)} (not shown).")
    print("Fill in by hand: APP_DOMAIN, ACME_EMAIL, PUBLIC_BASE_URL, CORS_ORIGINS, MAIN_URL, TRAINING_URL, DIRECTOR_EMAIL, DIRECTOR_NAME; later BACKUP_REMOTE, SMTP, Kylas.")
    print("Keep a copy of BACKUP_KEY off the server (a password manager): without it no backup can be opened.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
