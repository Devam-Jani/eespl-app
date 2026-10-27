# Deploying the EESPL App

The runbook for the production server: first deploy, users, backups, updates, rollback and
restore. Everything here was run on the development PC first (a local production run on
https://localhost); only the server itself is new.

Roles, never names: "the director", "the office admin". Never paste a password, key or the
contents of `.env` into a chat, ticket, email or this file.

## 1. The server

| | |
|---|---|
| OS | Ubuntu 24.04 LTS |
| Size | 4 vCPU, 8 GB RAM, 100 GB SSD |
| Region | Mumbai (data stays in India; location data never leaves this server) |
| Open ports | 22 from our office IP only, 80, 443 |

What runs on it (`docker-compose.prod.yml`, project `eespl-prod`):

| Container | Job |
|---|---|
| caddy | HTTPS (Let's Encrypt), security headers, the only container with ports (80, 443) |
| web | the built frontend (nginx, static files) |
| api, worker | the app and its background jobs (alerts, escalations, missed-backup check) |
| db | Postgres 16: the real company (`eespl`) and the training company (`eespl_training`) |
| osrm | road distances for travel claims (our own map data, no outside routing service) |
| backup | the nightly backup, the retention and the off-site copy |
| api-training, worker-training | the training company at `training.<domain>`, reset nightly |

Every container restarts on failure and keeps 5 × 10 MB of logs.

## 2. Before the server: what the director confirms

- The provider and the server (above).
- The domain, e.g. `app.<company-domain>`, and who can edit its DNS.
- The off-site backup target: an S3-compatible bucket (provider, region, bucket) or another
  rclone remote. Not the same provider account as the server.
- Whether staff email is turned on (`EMAIL_ENABLED`, staff only, never clients). It stays off
  until the director says so.
- Kylas: stays pointed at the sandbox until the director confirms the switch.

## 3. DNS

Two A records to the server's IPv4 address (and AAAA if it has IPv6):

```
app.<company-domain>            A   <server IP>
training.app.<company-domain>   A   <server IP>
```

Check from any PC: `nslookup app.<company-domain>` gives the server's IP. Caddy fetches the
certificates on the first start; it needs both names resolving and port 80 open.

## 4. The server's first hour

As root, once:

```sh
adduser eespl && usermod -aG sudo eespl
# SSH keys only, no root login
mkdir -p /home/eespl/.ssh && cp ~/.ssh/authorized_keys /home/eespl/.ssh/ && chown -R eespl: /home/eespl/.ssh
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/; s/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# firewall: 22 from the office only, then the web
ufw default deny incoming && ufw default allow outgoing
ufw allow from <office IP> to any port 22 proto tcp
ufw allow 80/tcp && ufw allow 443/tcp
ufw enable

# updates
apt update && apt -y upgrade && apt -y install unattended-upgrades git python3
timedatectl set-timezone Asia/Kolkata
```

Docker's published ports bypass ufw, which is why only Caddy publishes any (80 and 443).

Docker (the official repository):

```sh
curl -fsSL https://get.docker.com | sh
usermod -aG docker eespl
```

Log in again as `eespl` for the rest.

## 5. First deploy

```sh
git clone https://github.com/Devam-Jani/eespl-app.git /srv/eespl && cd /srv/eespl
git checkout <release tag>

# 1. the server's .env: fresh secrets (never the development ones), mode 600, nothing printed
python3 scripts/make-prod-secrets.py
# 2. fill the rest of .env: APP_DOMAIN, ACME_EMAIL, PUBLIC_BASE_URL, CORS_ORIGINS, MAIN_URL,
#    TRAINING_URL, DIRECTOR_EMAIL, DIRECTOR_NAME, BACKUP_REMOTE + RCLONE_CONFIG_OFFSITE_* (section 7)
nano .env

# 3. the road map for travel claims (about 20 minutes, once)
sh scripts/osrm-prepare.sh

# 4. check the configuration (prints no secret)
docker compose -f docker-compose.prod.yml config --quiet && echo ok

# 5. build and start
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

**Keep a copy of `BACKUP_KEY` off the server** (the director's password manager). Without it no
backup can be opened. `make-prod-secrets.py` writes it only into `.env`; copy it from there by hand.

The api runs the migrations on start. The real database starts with the seed only (roles,
permissions, settings, the process rules): no DEMO rows. To make a clean database by hand:

```sh
docker compose -f docker-compose.prod.yml exec api python -m app.cli go-live --database eespl
```

Check:

```sh
curl -s https://app.<company-domain>/health        # {"status": "ok", ...}: db, worker, osrm, backup
docker compose -f docker-compose.prod.yml exec api alembic current
```

## 6. The first users and the company's data

1. **The director's login**:
   ```sh
   docker compose -f docker-compose.prod.yml exec api python -m app.cli create-director
   docker compose -f docker-compose.prod.yml exec api python -m app.cli set-password <director email>
   ```
   The director signs in and turns on two-step sign-in (Settings > Security asks it of the
   director, the office admin and accounts once "required" is ticked).
2. **The company settings**: the yellow "not set" banner lists what is missing: legal name and
   PAN, GSTIN with its address, the bank, HSN codes on products, the letterhead's signatory
   and designation. The office admin clears it.
3. **Masters and libraries from the development PC** (products, vendors, clients, the rate
   library, BOQ knowledge, methodology, the active sites with their stages). No DEMO rows, and
   nothing still in the products review queue:
   ```sh
   # on the development PC
   docker compose exec -T db pg_dump -U eespl -Fc eespl > eespl-dev.dump
   scp eespl-dev.dump eespl@<server>:/srv/eespl/data/
   # on the server: into a scratch database, carried over, then dropped
   docker compose -f docker-compose.prod.yml exec -T db createdb -U eespl eespl_dev
   docker compose -f docker-compose.prod.yml exec -T db pg_restore -U eespl -d eespl_dev --no-owner < data/eespl-dev.dump
   docker compose -f docker-compose.prod.yml exec api python -m app.cli carry-over \
       --from postgresql+psycopg://eespl:<password from .env>@db:5432/eespl_dev --dry-run
   # read the counts and the skipped rows with their reasons, then without --dry-run
   docker compose -f docker-compose.prod.yml exec -T db dropdb -U eespl eespl_dev && rm data/eespl-dev.dump
   ```
   Running it again adds nothing twice.
4. **Users**: Administration > User import. Download the template (it lists the roles and the
   sites), fill one row per person (name, email, phone, roles, manager, sites, tracked, travel
   eligible, rate per km), upload, read the errors and fix them in the sheet. Nothing is saved
   until every row passes. Each person gets a one-time set-password link, which the office admin
   sends on our own channel (no email to clients; staff email only when `EMAIL_ENABLED`).
5. **Sign-off**: Administration > Who sees what (roles) > PDF, signed by the director.

## 7. Backups

The `backup` container runs nightly at `BACKUP_HOUR`. Each night makes one archive:
`pg_dump` (custom format) plus the media volume, with a manifest of row counts, encrypted with
`BACKUP_KEY` (gpg, AES-256). It keeps 14 daily, 8 weekly and 12 monthly archives, and copies
them off-site when `BACKUP_REMOTE` is set.

Off-site (S3-compatible bucket shown), in `.env`:

```
BACKUP_REMOTE=offsite:<bucket>/eespl
RCLONE_CONFIG_OFFSITE_TYPE=s3
RCLONE_CONFIG_OFFSITE_PROVIDER=<provider>
RCLONE_CONFIG_OFFSITE_ENDPOINT=<endpoint>
RCLONE_CONFIG_OFFSITE_REGION=<region>
RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID=<key id>
RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY=<secret>
```

then `docker compose -f docker-compose.prod.yml up -d backup`. Use a key that can write to the
bucket but not delete (or turn on the bucket's object lock): a stolen server must not wipe
the copies.

Run one now and check it:

```sh
docker compose -f docker-compose.prod.yml exec backup python3 /opt/backup/backup.py run
```

Administration > Backups and storage shows the last backup's time, size and off-site copy, and
the media size. A missed night alerts the director and the office admin (and /health turns
"degraded").

**Test a restore every month** into a scratch database (the live one is not touched):

```sh
sh scripts/restore.sh                                     # lists the archives
sh scripts/restore.sh eespl-<date>.tar.gpg eespl_check    # restores and compares row counts
docker compose -f docker-compose.prod.yml exec -T db dropdb -U eespl eespl_check
```

"differences": none means every table came back with the archive's counts.

## 8. Updating

```sh
cd /srv/eespl
docker compose -f docker-compose.prod.yml exec backup python3 /opt/backup/backup.py run   # a backup first
PREV=$(git rev-parse HEAD)                                    # the release running now
git fetch --tags && git checkout <new release tag>
docker compose -f docker-compose.prod.yml up -d --build      # the api migrates on start
curl -s https://app.<company-domain>/health
# the issue log book: the issues fixed by a commit of this release are marked released
docker compose -f docker-compose.prod.yml exec api python -m app.cli issues-released $(git log --format=%h $PREV..HEAD)
```

Write down the previous tag first (`git describe --tags`). Updates go in the evening, after
site reports are in.

## 9. Rollback

When the new release misbehaves and its migration changed nothing destructive:

```sh
git checkout <previous tag>
docker compose -f docker-compose.prod.yml exec api alembic downgrade <previous release's head>
docker compose -f docker-compose.prod.yml up -d --build
```

The release notes give each release's migration head. When a downgrade is not possible, restore
the backup taken just before the update (section 10).

## 10. Restoring the live database

Only when the database is lost or damaged. Everything entered since that backup is lost, so
the director decides.

```sh
cd /srv/eespl
docker compose -f docker-compose.prod.yml stop api worker caddy        # nobody writes meanwhile
# the backup container sees the media read-only; a one-off one writes it back
docker compose -f docker-compose.prod.yml run --rm -v eespl-prod_media:/media-restore backup \
    python3 /opt/backup/backup.py restore eespl-<date>.tar.gpg --into eespl --drop --media /media-restore
docker compose -f docker-compose.prod.yml up -d
curl -s https://app.<company-domain>/health
```

From the off-site copy when the server itself is gone: a new server (sections 4 and 5, with the
**same** `BACKUP_KEY`), then
`docker compose -f docker-compose.prod.yml exec backup rclone copy offsite:<bucket>/eespl /backups`
and the restore above.

## 11. The training company

`training.<domain>` is a separate company on the same server: the DEMO data and the real
users' logins (same passwords), reset every night at 03:30. Nothing done there reaches the real
company, and it sends nothing. Everyone reaches it from the menu: "Practise in the training
company".

## 12. The helper and the issue log book

Every request has an id (`X-Request-ID`); every 5xx is kept in the issue log book with it and its
trace (Settings > Issue log: the director, the office admin and the super admin). The browser adds
crashes and failed requests (the page, the role, the last button pressed, the error, the browser:
never what was typed, unless the user ticks "also send what I typed"; never a password or token).
Each user follows their own reports under My work > My reports (clients: "My reports" in the portal).

In `.env`:

- `HELPER_AI_ENABLED=true` turns on "Ask the helper" (Claude, `HELPER_AI_MODEL`, default
  claude-sonnet-5-5) with `ANTHROPIC_API_KEY`. Off by default. It only answers: it never changes
  data. What it is sent is scrubbed: no password, key, token, email, phone or place, and for a
  client user no amount, cost, rate, price or margin. Its answers are kept with the issue.
- `CRAWLER_TOKEN` (a long random value, `python scripts/make-prod-secrets.py` style): the nightly
  check's key to add its findings, and the GitHub workflow's key to read the open bugs. It opens
  nothing else.

Nightly at 02:00 the worker writes the open bugs (no personal data) to
`media/issues/open.md`; `python -m app.cli issues-open-md` writes it now. Mondays at 08:00 the
week's summary goes to the bell of the log book's keepers.

**The nightly check** (`tools/crawler`): after the training company's 03:30 rebuild, it signs in
there as each role's DEMO user and the DEMO client, opens every page of the menu, and reports
console errors, failed requests, blank screens, buttons that do nothing and pages over 2 s, as
"found by the nightly check". On the server, from cron at 04:30:

```sh
30 4 * * * cd /srv/eespl/tools/crawler && docker run --rm --network host -v "$PWD":/c -w /c   -e BASE=https://training.<company-domain> -e REPORT_URL=https://app.<company-domain>/api/issues/nightly   --env-file /srv/eespl/.env mcr.microsoft.com/playwright:v1.49.1-noble   sh -c "npm ci --silent && node crawl.cjs" >> /var/log/eespl-crawler.log 2>&1
```

(`.env` gives it `DEMO_USER_PASSWORD` and `CRAWLER_TOKEN`; it prints neither.)

**The developer agent** (`.github/workflows/fix-issues.yml`, claude-code-action pinned by its
commit): on weekdays at 06:00 IST, or by hand from the Actions tab (optionally one issue number),
it reads the open bugs from `/api/issues/nightly/open.md`, reproduces each with a failing test,
fixes it and opens a pull request "Fixes issue #N". It never merges or deploys. Set in GitHub
(Settings > Secrets and variables > Actions): the secret `ANTHROPIC_API_KEY` (a key for the agent,
separate from the app's), the secret `CRAWLER_TOKEN` (the same value as the server's) and the
variable `EESPL_URL` (`https://app.<company-domain>`). After review and merge, write the cause, the
fix, the pull request link and the commit on the issue (Settings > Issue log); the deploy that
carries the commit marks it released (section 8).

## 13. Pre-go-live checklist

- [ ] The server, the domain and the off-site target confirmed by the director
- [ ] DNS for the domain and `training.` resolves to the server
- [ ] Firewall: 22 from the office only, 80, 443; root login and SSH passwords off
- [ ] `.env` made by `make-prod-secrets.py` (fresh secrets), mode 600, `BACKUP_KEY` copied off the server
- [ ] `docker compose -f docker-compose.prod.yml config --quiet` passes
- [ ] https://app.<domain>/health is "ok" (db, worker, osrm, backup)
- [ ] The certificate is valid; `curl -I` shows HSTS, CSP and X-Frame-Options
- [ ] The database has no DEMO rows (the go-live check) and the masters carry-over ran (dry run read first)
- [ ] The "not set" banner is empty: GSTIN, address, bank, HSN codes, letterhead signatory and designation
- [ ] Users imported with no errors; each set their password from their link
- [ ] Two-step sign-in on for the director, the office admin and accounts
- [ ] The roles report signed by the director
- [ ] First backup made, copied off-site, and restored into a scratch database with no differences
- [ ] A missed-backup alert seen once (stop the backup container for a day on the training company, or trust the test)
- [ ] Each role's training PDF handed out; everyone has practised in the training company
- [ ] `EMAIL_ENABLED` as the director decided (staff only, never clients)
- [ ] Kylas still pointed at the sandbox until Devam confirms

## 14. Behind an existing nginx (the shared test server)

For a server where another web server already holds 80 and 443 (the test server lent by a friend:
its system nginx serves about 30 sites, and we have no sudo). `docker-compose.behind-proxy.yml`
is laid over the production file:

- compose project **`eespl-test`**: every container, network and volume starts with it;
- one published port, on the loopback only: **`127.0.0.1:9400`**. Our Caddy answers plain HTTP
  there (`deploy/behind-proxy/Caddyfile`), routes `training.<domain>` to the training company and
  everything else to the app, keeps the security headers, and trusts the host's
  `X-Forwarded-Proto` (the cookies stay Secure);
- every other service on an internal network (`eespl-test_back`): nothing published, no route out.
  The helper needs one: if `HELPER_AI_ENABLED` and `ANTHROPIC_API_KEY` are set, add `front` to the
  api's networks in the override;
- limits on every service, 3.5 GB and 3 CPUs in all:

  | service | memory | CPUs | | service | memory | CPUs |
  |---|---|---|---|---|---|---|
  | db | 512 MB | 0.50 | | worker-training | 384 MB | 0.20 |
  | api (3 workers) | 1024 MB | 0.75 | | osrm (`--mmap`) | 512 MB | 0.30 |
  | worker | 320 MB | 0.25 | | backup | 256 MB | 0.25 |
  | api-training | 384 MB | 0.40 | | caddy | 128 MB | 0.25 |
  | web | 64 MB | 0.10 | | **total** | **3584 MB** | **3.00** |

- no company data: the api's `/data` is the empty `deploy/behind-proxy/empty-data`. The main
  database gets the DEMO data, and the training company resets itself as usual. Real company data
  only when the director asks.
- `EESPL_STORE` in `.env`: a folder of ours on the big disk holding `osrm/` (the road map, made
  there by `osrm-prepare.sh`) and `backups/` (kept 7 days, no off-site copy);
- email, Kylas and the helper off.

`python3 scripts/check-behind-proxy.py` checks all of this on the resolved configuration (CI runs
it): only 127.0.0.1:9400 published, every service limited, no `data/` mount, internal networks.

### Deploy

No git credentials on the server: the code goes over ssh as an archive of the commit.

```sh
# on the PC
git archive --format=tar.gz -o eespl.tar.gz <commit>
scp eespl.tar.gz devam@<server>:~/eespl-test.tar.gz
python3 scripts/make-prod-secrets.py --out .env.test-server --dev-env .env   # fresh, mode 600
#   + APP_DOMAIN, PUBLIC_BASE_URL, CORS_ORIGINS, MAIN_URL, TRAINING_URL, EESPL_STORE, CRAWLER_TOKEN
scp .env.test-server devam@<server>:~/eespl-test/.env      # then chmod 600 there; never cat it

# on the server, in ~/eespl-test only
tar -xzf ~/eespl-test.tar.gz -C ~/eespl-test
mkdir -p "$EESPL_STORE/osrm" "$EESPL_STORE/backups"
# the road map, in EESPL_STORE (public OpenStreetMap data, not company data): once, before the
# stack starts, in one detached container (it survives the ssh session); osrm-extract needs about
# 8 GB for western India (4 GB is killed), about 10 minutes
curl -fL -o "$EESPL_STORE/osrm/western-zone-latest.osm.pbf" https://download.geofabrik.de/asia/india/western-zone-latest.osm.pbf
docker run -d --name eespl-test-osrm-prep --memory 8g --memory-swap 8g --cpus 2 -v "$EESPL_STORE/osrm:/data"   ghcr.io/project-osrm/osrm-backend:v5.27.1 sh -c "osrm-extract -p /opt/car.lua /data/western-zone-latest.osm.pbf   && osrm-partition /data/western-zone-latest.osrm && osrm-customize /data/western-zone-latest.osrm"
docker wait eespl-test-osrm-prep && docker rm eespl-test-osrm-prep      # 0 = done
C="docker compose -p eespl-test -f docker-compose.prod.yml -f docker-compose.behind-proxy.yml --env-file .env"
ENV_FILE=.env $C up -d --build
$C ps
curl -s -o /dev/null -w "%{http_code}\n" -H "Host: <domain>" http://127.0.0.1:9400/api/health
curl -s -o /dev/null -w "%{http_code}\n" -H "Host: training.<domain>" http://127.0.0.1:9400/api/health
docker stats --no-stream $(docker ps -q --filter label=com.docker.compose.project=eespl-test)
# the DEMO company in the main database (the training company seeds itself); a one-off container:
# inside the running api, next to its 3 workers, it would pass the api's memory limit
ENV_FILE=.env $C run --rm -T --no-deps api python -c "import app.main; from app.ops import training; print(training._seed_demo())"
# the super admin: the password on stdin, never on the command line
ENV_FILE=.env $C run --rm -T --no-deps api python -m app.cli create-admin --email <role address> --name "Super admin" < password-file
```

Never `docker system/image/volume/network prune` or `compose down` outside this folder on a
shared server: those remove other people's things.

The server's owner adds the nginx site (`deploy/behind-proxy/nginx-site.conf`: both names to
127.0.0.1:9400, websocket headers, 200 MB uploads, 10-minute timeouts) and the certificate; the
steps are in `deploy/behind-proxy/FOR-THE-SERVER-OWNER.md`.

Before DNS, check through a tunnel: `ssh -L 9400:127.0.0.1:9400 devam@<server>`, then
http://localhost:9400 (the app) and http://training.localhost:9400 (the training company). The
browser treats both as secure, so the Secure cookies work over plain HTTP there.

### Moving to the new server

1. **On the old server**, a backup, and copy it off:

   ```sh
   $C exec backup python3 /opt/backup/backup.py run
   scp devam@<old>:$EESPL_STORE/backups/eespl-<date>.tar.gpg .
   ```

   Keep the old `.env`'s `BACKUP_KEY`: the archive opens only with it.
2. **On the new server**, sections 4 and 5 as usual (it owns 80/443, so no override). Use a
   **fresh** `.env`, but carry over the old `BACKUP_KEY`, then restore:

   ```sh
   docker compose -f docker-compose.prod.yml cp eespl-<date>.tar.gpg backup:/backups/
   docker compose -f docker-compose.prod.yml stop api worker caddy
   docker compose -f docker-compose.prod.yml run --rm -v eespl-prod_media:/media-restore backup \
       python3 /opt/backup/backup.py restore eespl-<date>.tar.gpg --into eespl --drop --media /media-restore
   docker compose -f docker-compose.prod.yml up -d
   ```

   The training company needs no copy: it rebuilds itself from the DEMO data.
3. **Switch DNS**: point the A records for `<domain>` and `training.<domain>` at the new server.
   Lower their TTL to 300 a day before. Caddy fetches the certificate once they resolve.
4. **Clean up the old server** (our things only): `$C down -v` in `~/eespl-test`, then remove
   `~/eespl-test` and `$EESPL_STORE`. The backups are root's files, so remove them with
   `docker run --rm -v $EESPL_STORE:/s alpine rm -rf /s/backups /s/osrm`. Ask the owner to remove
   the nginx site and the certificate (the undo steps in the note).
