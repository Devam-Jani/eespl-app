# ruff: noqa: E501
"""Check the behind-a-proxy stack (docker-compose.prod.yml + docker-compose.behind-proxy.yml) as
docker compose resolves it:

    python3 scripts/check-behind-proxy.py

- the only published port is 127.0.0.1:9400 (Caddy); nothing on 0.0.0.0;
- every service has a memory and a CPU limit, about 4 GB and 3 CPUs in all at most;
- no service mounts the repository's data/ folder (company drawings, BOQs, billing samples);
- every service but Caddy is on internal networks only;
- the project, and so every container, network and volume, is named eespl-test;
- its Caddyfile keeps the security headers and trusts the host's X-Forwarded-Proto.

Runs `docker compose config` with a throwaway env file of dummy values (no secret is read).
Standard library only; exits 1 and lists what is wrong."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "eespl-test"
PORT = ("127.0.0.1", "9400")
MAX_MEMORY = 4 * 2**30
MAX_CPUS = 3.0
DUMMY = {
    "APP_DOMAIN": "eespl.example.com",
    "EESPL_STORE": "/srv/eespl-test-store",
    "POSTGRES_DB": "eespl",
    "POSTGRES_USER": "eespl",
    "POSTGRES_PASSWORD": "dummy",
    "TILE_HOST": "tile.openstreetmap.org",
}


def resolved_config() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        env = Path(tmp) / "env"
        env.write_text("".join(f"{k}={v}\n" for k, v in DUMMY.items()), encoding="utf-8")
        cmd = ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.prod.yml", "-f", "docker-compose.behind-proxy.yml", "--env-file", str(env), "config", "--format", "json"]
        out = subprocess.run(cmd, cwd=ROOT, env={**os.environ, "ENV_FILE": str(env)}, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def problems(cfg: dict) -> list[str]:
    bad = []
    if cfg.get("name") != PROJECT:
        bad.append(f"project name is {cfg.get('name')!r}, not {PROJECT}")
    internal = {name for name, n in cfg.get("networks", {}).items() if n.get("internal")}
    data = (ROOT / "data").resolve()
    published, memory, cpus = [], 0, 0.0
    for name, svc in sorted(cfg["services"].items()):
        for p in svc.get("ports", []):
            published.append((name, p.get("host_ip", ""), str(p.get("published", ""))))
        limits = svc.get("deploy", {}).get("resources", {}).get("limits", {})
        if not limits.get("memory") or not limits.get("cpus"):
            bad.append(f"{name}: no memory or CPU limit")
        memory += int(limits.get("memory") or 0)
        cpus += float(limits.get("cpus") or 0)
        for v in svc.get("volumes", []):
            if v.get("type") == "bind":
                src = Path(v["source"]).resolve()
                if src == data or data in src.parents:
                    bad.append(f"{name}: mounts the repository's data/ folder ({v['target']})")
        nets = set(svc.get("networks", {}))
        if name != "caddy" and (not nets or nets - internal):
            bad.append(f"{name}: on a network that is not internal ({sorted(nets - internal) or ['default']})")
    caddy = (ROOT / "deploy/behind-proxy/Caddyfile").read_text(encoding="utf-8")
    for needed in ("Strict-Transport-Security", "Content-Security-Policy", "X-Frame-Options", "frame-ancestors 'none'", "trusted_proxies static private_ranges", ":9400"):
        if needed not in caddy:
            bad.append(f"deploy/behind-proxy/Caddyfile: no {needed}")
    if published != [("caddy", *PORT)]:
        bad.append(f"published ports should be only caddy on {':'.join(PORT)}, found {published}")
    if memory > MAX_MEMORY:
        bad.append(f"memory limits add up to {memory / 2**30:.2f} GiB (at most {MAX_MEMORY / 2**30:.0f})")
    if cpus > MAX_CPUS + 1e-9:
        bad.append(f"CPU limits add up to {cpus:.2f} (at most {MAX_CPUS})")
    return bad


def main() -> int:
    cfg = resolved_config()
    bad = problems(cfg)
    for line in bad:
        print("FAIL", line)
    if not bad:
        services = cfg["services"]
        mem = sum(int(s["deploy"]["resources"]["limits"]["memory"]) for s in services.values())
        cpu = sum(float(s["deploy"]["resources"]["limits"]["cpus"]) for s in services.values())
        print(f"ok: {len(services)} services, only {':'.join(PORT)} published, limits {mem / 2**30:.2f} GiB and {cpu:.2f} CPUs, no data/ mount, internal networks")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
