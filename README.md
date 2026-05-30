# SIGLOG

Portable signal collector: RTL-SDR + GPS on a Raspberry Pi Zero 2W, live UI on an Adafruit ESP32-S3 Reverse TFT Feather.

## Hardware

| Part | Role |
|------|------|
| Raspberry Pi Zero 2W | ADS-B (dump1090), GPS (NEO-6M on UART), API, SQLite log |
| RTL-SDR R820T2 TCXO + dipole kit | 1090 MHz ADS-B (later NOAA/APRS/AIS) |
| u-blox NEO-6M TTL | Geo-tag every catch |
| Micro USB OTG adapter | RTL-SDR on the Pi’s USB OTG port |
| ESP32-S3 Reverse TFT Feather | 240×135 display, WiFi client (same LAN as Pi) |
| LiPo 2500 mAh + TP4056 | Pi + SDR power |
| LiPo 500 mAh JST | Feather display power |

Pi and Feather talk over WiFi only (no GPIO link). GPS uses pins 1, 6, 8, 10.

## Software layout

```
apps/pizero2w/     Docker stack (dump1090, gpsd, Flask API)
apps/esp32/        Feather firmware (ESP-IDF, planned)
```

## Pi Zero for testing

1. Flash **Raspberry Pi OS Lite (64-bit)** via Raspberry Pi Imager (SSH + home WiFi in advanced options).
2. **Mac** (after code changes): `just push-pizero` (or `just release-pizero`).
3. **Pi** (first time): clone repo or copy `justfile`, then `sudo apt install -y just` and `just setup-on-pi`.
4. **Pi** (every update): `cd ~/siglog && just update-on-pi`. Never `docker compose build` on the Pi. GPS overlay only with `SIGLOG_GPS=1 just update-on-pi` when the NEO-6M is wired (UART enabled ≠ module present).
5. **Mac** dev without SDR: `just run-pizero-fake` — API on http://localhost:8080

| Command | Where | What |
|---------|-------|------|
| `just push-pizero` | Mac | Build ARM64 image + push to GHCR |
| `just update-on-pi` | Pi | Pull image + `up --no-build` |
| `just net-auto` | Pi | WiFi home-first + hotspot fallback |

**WiFi (one-time on Pi):** `siglog-net auto` — at home the Pi uses your router; outdoors it starts hotspot `siglog-pi` after ~25s without internet. Before leaving you only need `siglog-net leave` once (optional). Status: `siglog-net status`. Emergency: `siglog-net hotspot` / `siglog-net wifi`.

**Do not** compile dump1090 on the Pi (`git clone` + `make`). Trixie has no `dump1090-fa` apt package; use the container image instead.

ESP32 can point at `http://<pi-lan-ip>/api/latest` on the same LAN.

## API

- `GET /api/latest` - current signal for the handheld UI (ADS-B or active NOAA pass)
- `GET /api/passes` - next NOAA-15/18/19 passes (TLE + Skyfield), notify ~15 min before
- `GET /api/history` - last 100 logged signals
- `GET /api/health` - status

**One RTL-SDR:** ADS-B runs by default; ~15 min before a satellite pass the API shows `nextPass` and antenna hint (~54 cm dipole). NOAA 15/18/19 were **decommissioned in 2025** — pass prediction uses **Meteor-M** satellites from Celestrak instead. Auto APT decode via `noaa-apt` only applies if legacy NOAA TLE entries reappear; Meteor LRPT decode is planned separately.

Set observer position via GPS (when connected) or `SIGLOG_LAT` / `SIGLOG_LON` in `docker-compose.yml` (default Berlin).
