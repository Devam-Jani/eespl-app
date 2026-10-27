# EESPL test app: what we need from the server's owner

Hello, and thank you for lending us room on vm-noesis-prod-ci-01, and for making
`/data/projects/eespl-test` for us.

We are running a test copy of the EESPL App on the server until it passes its checks; then it
moves to its own server. Here is what we set up and the few steps that need sudo, which our
account doesn't have.

## What we run (nothing of yours is touched)

- Docker compose project **`eespl-test`**, from `/data/projects/eespl-test` only: every
  container, network and volume starts with `eespl-test`. Backups (kept 7 days) and the road map
  are in that folder too.
- One port only, on the loopback: **`127.0.0.1:9400`** (plain HTTP). The database and everything
  else are on an internal docker network, not published.
- Limits on every container: about **3.6 GB of RAM and 3 CPUs** in all.
- No email is sent, and no outside service is called.

## The two names

| Name | What |
|---|---|
| `eespl.noesisanalytics.co.in` | the app |
| `eespl-training.noesisanalytics.co.in` | the training company (practice data, rebuilt every night) |

Both go to the same port. Our side tells them apart by the Host header, so nginx only has to
pass it through. We understand your team handles DNS (A records to 20.204.77.70).

## The steps that need sudo

1. The nginx site. The file is `/data/projects/eespl-test/deploy/behind-proxy/nginx-site.conf`.
   It proxies both names to 127.0.0.1:9400, with Host, X-Forwarded-For, X-Forwarded-Proto,
   websocket upgrade, 200 MB uploads (600 MB for one model upload) and 10-minute timeouts for large
   drawings.

   ```
   sudo cp /data/projects/eespl-test/deploy/behind-proxy/nginx-site.conf /etc/nginx/sites-available/eespl
   sudo ln -s /etc/nginx/sites-available/eespl /etc/nginx/sites-enabled/eespl
   sudo nginx -t
   sudo systemctl reload nginx
   ```

2. The certificate, once DNS answers:

   ```
   sudo certbot --nginx -d eespl.noesisanalytics.co.in -d eespl-training.noesisanalytics.co.in
   ```

To undo everything later: remove the two files from `/etc/nginx/sites-*/`, `sudo nginx -t`,
reload nginx, `sudo certbot delete --cert-name eespl.noesisanalytics.co.in`. We remove our
containers and the folder's contents ourselves.

## A friendly heads-up from our read-only look around

While checking which ports were free, we noticed that several database and cache ports are
published on all interfaces (0.0.0.0): PostgreSQL on 5440-5444, 6500, 7003, 7055, 9503, 9563, 9099,
9630, 9660 and 9700; MySQL on 6000; Redis on 9508, 9568, 9631 and 9661; and Ollama on 11434. We
couldn't see the firewall from our account, so they may already be closed. If they aren't, the
Azure network security group is the easiest place to check and close them.

Thank you!
