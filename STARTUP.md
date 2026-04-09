# Local Startup Guide

## Prerequisites

- Python 3.10+ with `.venv` created and dependencies installed
- `devtunnel` CLI authenticated (`devtunnel login`)
- Azure Communication Services resource configured in `.env`

## 1. Dev Tunnel

The app needs an HTTPS tunnel so ACS can deliver webhooks (`/call/events`) and open WebSocket media streams (`/media/{token}`).

**Tunnel ID:** `swift-hill-t9dzp4x` (region: usw2)  
**Public URL:** `https://n3st3xsb-8000.usw2.devtunnels.ms`

```bash
# Start the tunnel
devtunnel host swift-hill-t9dzp4x
```

### If the tunnel or port needs to be recreated

```bash
devtunnel create --allow-anonymous
devtunnel port create <tunnel-id> -p 8000 --protocol http
```

**Critical notes:**
- Port protocol must be `http` — devtunnel terminates TLS externally and forwards plain HTTP/WS to uvicorn. Using `https` causes `Invalid HTTP request received` errors because uvicorn doesn't speak TLS.
- `--allow-anonymous` is required so ACS can reach the callback and WebSocket endpoints without auth.
- The `-inspect` URL (e.g. `*-inspect.usw2.devtunnels.ms`) is for browser debugging only — **never** use it as `APP_BASE_URL`.
- If the tunnel URL changes, update `APP_BASE_URL` in `.env`.

## 2. Start the App

In a separate terminal:

```bash
source scripts/load_env.sh
./scripts/start.sh
```

## 3. Make a Call

In a third terminal:

```bash
./scripts/make_call.sh
```

For a dry run without PSTN, edit the payload to `"simulate": true`.

## 4. Monitor (optional)

```bash
./scripts/poll_status.sh
tail -f logs/app.log
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `make_call.sh` gets no response | App not running or tunnel down | Ensure both `devtunnel host` and `start.sh` are running |
| Tunnel suddenly stops working | Multiple `devtunnel host` processes — second one kicks the first off | Kill all: `taskkill /F /IM devtunnel.exe`, then start one instance |
| `Invalid HTTP request received` from uvicorn | Devtunnel port protocol set to `https` | Recreate port with `--protocol http` |
| ACS callbacks never arrive | `APP_BASE_URL` wrong (inspect URL, stale ngrok, etc.) | Set `APP_BASE_URL` to the actual devtunnel URL (no `-inspect`) |
| `No module named uvicorn` | Venv packages missing | `.venv\Scripts\activate && pip install -r requirements.txt` |
