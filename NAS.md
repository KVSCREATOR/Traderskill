# Running Tradeskill on the Synology NAS (DS925+)

Checked 17 Nov 2026: DS925+, DSM 7.4.1, 8 GB RAM, Container Manager, Git and Tailscale
installed, shared folder `docker` at `/volume1/docker` (SHR-protected volume). Nothing else
is needed.

Once it runs on the NAS it is on 24x7: paper accounts, GTT orders, alerts and the forward-test
journal keep working with your PC off, and you can open it from any device at home - or from
anywhere through Tailscale.

## 1. Copy the project to the NAS

From Windows File Explorer open `\\192.168.1.200\docker`, create a folder `tradeskill`, and
copy these into it from `D:\Projects\tradeskill`:

```
server.py  longterm.py  gtt.py  kite.py  nifty50.json  nifty250.json
static\    Dockerfile   docker-compose.yml   tradeskill.env.example
```

To keep your paper accounts, journal, alerts and settings, also copy the `data` folder.
(Leave it out to start fresh.)

## 2. Set the password and address

In `\\192.168.1.200\docker\tradeskill`, copy `tradeskill.env.example` to `tradeskill.env` and
edit it with Notepad:

```
PORTAL_PASSWORD=<your own password, 8+ characters>
PUBLIC_URL=http://192.168.1.200:8765
```

- To use it from outside home as well, open the **Tailscale** app on the NAS, note its
  Tailscale IP (starts with `100.`), and use `PUBLIC_URL=http://100.x.y.z:8765` instead.
  Your phone/laptop need the Tailscale app signed in to the same account.
- `tradeskill.env` holds your password: it is never uploaded to GitHub.

## 3. Start it in Container Manager

1. DSM -> **Container Manager** -> **Project** -> **Create**.
2. Project name `tradeskill`, Path `/docker/tradeskill`, Source: **Use existing
   docker-compose.yml**.
3. Next -> Next -> **Done**. It builds the image (about a minute, downloads `python:3.12-slim`)
   and starts the container. It restarts by itself after a NAS reboot.
4. Open `http://192.168.1.200:8765` (or your Tailscale address) and sign in with the password.

## 4. HTTPS address for Zerodha (required)

Zerodha only returns to an **HTTPS** address (or 127.0.0.1), so plain
`http://192.168.1.200:8765` is refused ("invalid_redirect_uri"). Use DSM's reverse proxy:

1. Control Panel -> Login Portal -> Advanced -> **Reverse Proxy** -> **Create**.
2. Description `Tradeskill portal`; Source **HTTPS**, hostname `*`, port **8766**;
   Destination **HTTP**, `localhost`, port **8765**. Save.
3. Set `PUBLIC_URL=https://192.168.1.200:8766` in `tradeskill.env` (or put that one line in
   `data/public_url.txt`, which overrides it without touching the password file).
4. Container Manager -> Project -> `tradeskill` -> **Action -> Build** (recreates the container).
5. Open **https://192.168.1.200:8766** in Chrome; accept the certificate warning once
   (Advanced -> Proceed: DSM's certificate is for its Synology name, not the IP).
6. Sign in -> **My holdings** -> **Connect Zerodha**. The portal registers the new address itself.

Use the https address from then on (bookmark it).

## 5. Stop the PC copy

Run only one copy at a time, otherwise the PC and the NAS keep separate paper accounts and
journals. After the NAS works, stop `start.bat` on the PC.

## Updating later

Copy the changed files over the old ones in `\\192.168.1.200\docker\tradeskill`, then in
Container Manager -> Project -> `tradeskill` -> **Action -> Build** (then Start). `data` and
`tradeskill.env` are kept.

## Safety

- Do not forward port 8765 on your router to the internet. Use Tailscale for outside access.
- Zerodha access stays read-only; the portal still cannot place real orders.
- The sign-in cookie lasts 30 days; changing `PORTAL_PASSWORD` signs everyone out.
