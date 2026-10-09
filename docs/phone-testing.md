# Testing the app on a phone (office network, HTTPS)

A phone browser only allows the camera (survey photos, the marker measure) and WebXR (AR measure)
on an HTTPS page. The `lan-https` profile puts a small Caddy proxy in front of the web app that
serves it over HTTPS on this PC's office-network address, with a certificate from its own local
certificate authority. It is for the office Wi-Fi only.

**Never expose it to the internet.** Do not add a port-forward for 8443 or 8080 on the router,
do not run it on a PC that has a public IP address, and stop it when you are done.

## 1. Start it

1. Find this PC's office-network address: run `ipconfig` and take the IPv4 address of the Wi-Fi
   or Ethernet adapter, for example `192.168.1.20`. It must be a private address
   (192.168.x.x, 10.x.x.x or 172.16–31.x.x).
2. Start the proxy (the rest of the app must already be running):

   ```sh
   LAN_IP=192.168.1.20 docker compose --profile lan-https up -d lan-https
   ```

   In PowerShell: `$env:LAN_IP="192.168.1.20"; docker compose --profile lan-https up -d lan-https`.
   The ports are bound to that address only (8443 for the app over HTTPS, 8080 for the
   certificate download). Without `LAN_IP` they bind to 127.0.0.1 and nothing leaves the PC.
3. The first time, Windows Defender Firewall may ask about Docker: allow it on **Private
   networks only**, never on public networks.

## 2. Trust the certificate on the Android phone (once)

The phone must be on the same office Wi-Fi.

1. In Chrome on the phone open `http://192.168.1.20:8080/eespl-local-root.crt` (your address).
   The file `eespl-local-root.crt` downloads.
2. Open **Settings → Security and privacy → More security settings → Encryption and
   credentials → Install a certificate → CA certificate** (the names differ a little between
   phone makers; search Settings for "CA certificate").
3. Accept the warning, pick the downloaded `eespl-local-root.crt`. It now shows under
   **Trusted credentials → User**.

The local certificate authority lives in `data/lan-https/` on this PC (gitignored). If that folder
is deleted, a new authority is made and the phone must trust the new file again. To remove it from
the phone later: Trusted credentials → User → the Caddy local authority → Remove.

## 3. Open the app

Open `https://192.168.1.20:8443` in Chrome on the phone and sign in as usual. The address bar
shows a lock; the camera asks for permission on the first survey photo.

- Marker photo, proof photo: work on any phone with a camera.
- AR measure: needs Chrome on an ARCore-supported Android phone; it is hidden where it is not
  available, with one line saying why.
- iPhone: install the certificate from Safari (it downloads as a profile), then Settings →
  General → VPN & Device Management → install, and Settings → General → About → Certificate
  Trust Settings → turn on full trust. WebXR AR is not available on iPhone.

## 4. Stop it

```sh
docker compose --profile lan-https stop lan-https
```

## Notes

- Caddy answers only requests from private (LAN) addresses. With Docker Desktop every request
  reaches the container from Docker's own internal address, so that check cannot tell office
  and outside callers apart there; the real protection is binding to the LAN address and never
  forwarding the ports. Keep it that way.
- Phones send no server name (SNI) when the address is a bare IP, so the proxy is configured with
  a default certificate for the LAN address (`default_sni`).
- The Vite dev server's live reload works through the proxy; if the page does not refresh after
  a code change, reload it by hand.
