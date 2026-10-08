# HTTPS for the phone demo (BE-07)

**Owner:** Coder 3. **Read this if** you open the app on a phone, or you run the demo.

Phone browsers only give a page the camera, the microphone and speech recognition over **HTTPS**. Opening `http://192.168.x.x:5173` on a phone shows the page, but the camera never starts. `localhost` is the only exception, and it only works on the laptop itself. The WebSocket then has to be `wss://` too.

There are two ways to get HTTPS:

| | Main path: Cloudflare tunnel | Fallback: hotspot + `mkcert` |
|---|---|---|
| Needs | internet on the laptop | nothing but the laptop and the phone |
| Phone network | any, including mobile data | the laptop's hotspot |
| Setup time | 1 minute | about 10 minutes the first time |
| Use when | always, by default | the venue Wi-Fi blocks tunnels, or there's no internet |

---

## 1. One-time install

| Tool | Windows | macOS |
|---|---|---|
| `cloudflared` | `winget install --id Cloudflare.cloudflared` | `brew install cloudflared` |
| `mkcert` (fallback only) | `winget install FiloSottile.mkcert` | `brew install mkcert` |

Open a **new** terminal after installing, so the new commands are found.

In `backend/.env`, set this once. It lets every new tunnel URL call the API, so you never have to edit `ALLOWED_ORIGINS` again:

```
ALLOWED_ORIGIN_REGEX=^https://[a-z0-9-]+\.trycloudflare\.com$
```

> Demo only: this lets any `trycloudflare.com` page call our API from a browser. Leave it empty outside the demo.

## 2. Main path: Cloudflare quick tunnels

Run each of these in its own terminal:

```bash
# 1. backend
cd backend && venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000

# 2. tunnels (prints the URLs and writes them into frontend/.env)
cd backend && venv\Scripts\activate
python -m tools.tunnels --write-env

# 3. frontend (start it after step 2, so Vite reads the new .env)
cd frontend && npm run dev -- --host
```

`tools.tunnels` prints something like this:

```
 Backend  https://brave-otter-sample-words.trycloudflare.com   (-> http://localhost:8000)
 Frontend https://quiet-lake-other-words.trycloudflare.com    (-> http://localhost:5173)
 Open on the phone (Wi-Fi off to test mobile data): https://quiet-lake-other-words.trycloudflare.com
 frontend/.env:
   VITE_API_BASE=https://brave-otter-sample-words.trycloudflare.com/api/v1
   VITE_WS_BASE=wss://brave-otter-sample-words.trycloudflare.com/ws
 Health through the tunnel: {"status":"degraded",...}
```

- **The URLs change on every start.** After a restart, rerun the command and restart Vite.
- **Leave the command running.** Ctrl+C stops both tunnels.
- **Before the frontend exists:** use `--backend-only`. You get just the API URL, for Postman or the check below.
- **Without `--write-env`,** it only prints the two `VITE_` lines. `frontend/.env` belongs to Coder 1.

### Check `wss://` through the tunnel

```bash
python -m tools.wss_check --base https://<backend>.trycloudflare.com
```

It sends `hello`, a JPEG frame and a `ping` over `wss://` and prints the timings, then `PASS`. It exits non-zero on failure.

### Test from mobile data

The phone, not the laptop, has to prove the tunnel works off the venue network:

1. Turn **Wi-Fi off** on the phone.
2. Open `https://<backend>/api/v1/health`. You should see the health JSON.
3. Open the frontend URL and allow the camera. The connection indicator should turn green.

## 3. Fallback: laptop hotspot + `mkcert`

Use this when tunnels don't come up: `tools.tunnels` reports no URL within 30 s, or the URL never loads.

1. **Start the laptop hotspot.** On Windows: Settings → Network → Mobile hotspot. Connect the phone to it. Then find the laptop's address on the hotspot:
   - **Windows:** usually `192.168.137.1`; check with `ipconfig`.
   - **macOS:** `ipconfig getifaddr bridge100`.
2. **Make certificates** (from the repo root):
   ```bash
   mkcert -install
   mkdir certs && cd certs
   mkcert -key-file key.pem -cert-file cert.pem 192.168.137.1 localhost 127.0.0.1
   ```
   Nothing in `certs/` is committed: `.gitignore` excludes it and `*.pem`. Never share `key.pem`.
3. **Trust the certificate on the phone.** Run `mkcert -CAROOT` to find `rootCA.pem` and copy that file to the phone. Install `rootCA.pem` only, never `key.pem`.
   - **Android (use Chrome):** Settings → Security → More security settings → Encryption & credentials → Install a certificate → **CA certificate**.
   - **iOS (Safari):** open the file to install the profile, then Settings → General → VPN & Device Management → install, then Settings → General → About → Certificate Trust Settings → turn on full trust.
4. **Start the backend with TLS:**
   ```bash
   cd backend
   uvicorn main:app --host 0.0.0.0 --port 8000 --ssl-keyfile ../certs/key.pem --ssl-certfile ../certs/cert.pem
   ```
   In `backend/.env`: `ALLOWED_ORIGINS=https://192.168.137.1:5173`
5. **Start Vite with TLS.** Coder 1 adds this to `vite.config.ts`, so it only switches on when the certs exist:
   ```ts
   import fs from "node:fs";
   const certs = "../certs";
   const https = fs.existsSync(`${certs}/key.pem`)
     ? { key: fs.readFileSync(`${certs}/key.pem`), cert: fs.readFileSync(`${certs}/cert.pem`) }
     : undefined;
   export default defineConfig({ server: { host: true, https } /* , ...rest */ });
   ```
   In `frontend/.env`:
   ```
   VITE_API_BASE=https://192.168.137.1:8000/api/v1
   VITE_WS_BASE=wss://192.168.137.1:8000/ws
   ```
6. **Open the app** on the phone at `https://192.168.137.1:5173`. Check it first with `python -m tools.wss_check --base https://192.168.137.1:8000`.

Member 5 times this switch in the network-failure drill (see the roadmap).

## 4. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| The page loads but the camera never starts | The page is on `http://` or a LAN IP | Use the tunnel URL, or the `mkcert` `https://` URL |
| `tools.tunnels`: "cloudflared is not installed" | Not on PATH | Install it (section 1), open a new terminal, or pass `--cloudflared <path>` |
| `tools.tunnels`: no URL within 30 s | The network blocks Cloudflare | Use the fallback (section 3) |
| A URL was printed, but the laptop says `getaddrinfo failed` | The new name hasn't reached your network's DNS yet, and Windows cached the early "not found" | Wait a minute, run `ipconfig /flushdns`, and retry. The tunnel itself is fine; the phone on mobile data usually resolves it sooner. |
| REST works, but the socket fails | `VITE_WS_BASE` is `ws://` or points at the frontend URL | It must be `wss://<backend>/ws` |
| A CORS error in the browser console | The frontend origin isn't allowed | Set `ALLOWED_ORIGIN_REGEX` (tunnel) or `ALLOWED_ORIGINS` (`mkcert`), then restart the backend |
| An old URL is dead | The tunnel was restarted | Rerun `tools.tunnels --write-env` and restart Vite |
| The phone says "certificate not trusted" (fallback) | `rootCA.pem` isn't trusted | Section 3 step 3. On iOS, full trust is a separate switch. |
