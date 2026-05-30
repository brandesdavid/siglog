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
2. On your **PC/Mac** (never on the Pi): `just build-pizero` then `just push-pizero` — dump1090 is built inside that image, not on the Zero.
3. On the Pi: `bash apps/pizero2w/setup.sh` — Docker pull + `up --no-build` only. No hotspot (keeps home WiFi for SSH). RTL udev rules included.
4. Dev on your PC: `just run-pizero-fake` — API on port 8080 with `FAKE_SIGNALS=1`.

**Outdoor / no home WiFi:** `~/siglog/scripts/pizero-hotspot-on.sh` — stop with `pizero-hotspot-off.sh`. Optional at setup: `SIGLOG_ENABLE_HOTSPOT=1 bash setup.sh`.

**Do not** compile dump1090 on the Pi (`git clone` + `make`). Trixie has no `dump1090-fa` apt package; use the container image instead.

ESP32 can point at `http://<pi-lan-ip>/api/latest` on the same LAN.

## API

- `GET /api/latest` - current signal for the handheld UI
- `GET /api/history` - last 100 logged signals
- `GET /api/health` - status
