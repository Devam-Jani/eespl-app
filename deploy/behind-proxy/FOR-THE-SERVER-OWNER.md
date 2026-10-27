# EESPL test app: what we need from the server's owner

Hello, and thank you for lending us room on vm-noesis-prod-ci-01.

We are running a test copy of the EESPL App on the server until it passes its checks; then it
moves to its own server. Here is what is already done and the few steps that need sudo, which our
account doesn't have.

## What is already there (nothing of yours was touched)

- Docker compose project **`eespl-test`**: every container, network and volume starts with
  `eespl-test`. Code in `~devam/eespl-test`; backups and the road map in
  `/data/docker_volumes/eespl-test`.
- One port only, on the loopback: **`127.0.0.1:9400`** (plain HTTP). The database and everything
  else are on an internal docker network, not published.
- Limits on every container: about **3.75 GB of RAM and 3 CPUs** in all.
- No email is sent, and no outside service is called.

## The steps that need sudo

The domain below is a placeholder, **`eespl.example.com`**. We will send the real one; replace it
in the commands and in the site file (3 places).

1. DNS (wherever the domain is managed): two A records to this server.

   ```
   eespl.example.com.            A   20.204.77.70
   training.eespl.example.com.   A   20.204.77.70
   ```

2. The nginx site. The file is `~devam/eespl-test/deploy/behind-proxy/nginx-site.conf`. It proxies
   both names to 127.0.0.1:9400, with Host, X-Forwarded-For, X-Forwarded-Proto, websocket upgrade,
   200 MB uploads (600 MB for one model upload) and 10-minute timeouts for large drawings.

   ```
   sudo cp ~devam/eespl-test/deploy/behind-proxy/nginx-site.conf /etc/nginx/sites-available/eespl
   sudo ln -s /etc/nginx/sites-available/eespl /etc/nginx/sites-enabled/eespl
   sudo nginx -t
   sudo systemctl reload nginx
   ```

3. The certificate, once the DNS records answer:

   ```
   sudo certbot --nginx -d eespl.example.com -d training.eespl.example.com
   ```

To undo everything later: remove the two files from `/etc/nginx/sites-*/`, `sudo nginx -t`,
reload nginx, `sudo certbot delete --cert-name eespl.example.com`. We remove our containers and
folders ourselves.

## A friendly heads-up from our read-only look around

While checking which ports were free, we noticed that several database and cache ports are
published on all interfaces (0.0.0.0): PostgreSQL on 5440-5444, 6500, 7003, 7055, 9503, 9563, 9099,
9630, 9660 and 9700; MySQL on 6000; Redis on 9508, 9568, 9631 and 9661; and Ollama on 11434. We
couldn't see the firewall from our account, so they may already be closed. If they aren't, the
Azure network security group is the easiest place to check and close them.

Thank you!
