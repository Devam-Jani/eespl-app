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
git fetch --tags && git checkout <new release tag>
docker compose -f docker-compose.prod.yml up -d --build      # the api migrates on start
curl -s https://app.<company-domain>/health
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

## 12. Pre-go-live checklist

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
