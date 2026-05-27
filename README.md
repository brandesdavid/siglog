# SIGLOG

Portable signal collector: RTL-SDR + GPS on a Raspberry Pi Zero 2W, live UI on an Adafruit ESP32-S3 Reverse TFT Feather.

## Hardware

| Part | Role |
|------|------|
| Raspberry Pi Zero 2W | ADS-B (dump1090), GPS (NEO-6M on UART), API, SQLite log |
| RTL-SDR R820T2 TCXO + dipole kit | 1090 MHz ADS-B (later NOAA/APRS/AIS) |
| u-blox NEO-6M TTL | Geo-tag every catch |
| Micro USB OTG adapter | RTL-SDR on the Pi’s USB OTG port |
| ESP32-S3 Reverse TFT Feather | 240×135 display, WiFi client to Pi hotspot |
| LiPo 2500 mAh + TP4056 | Pi + SDR power |
| LiPo 500 mAh JST | Feather display power |

Pi and Feather talk over WiFi only (no GPIO link). GPS uses pins 1, 6, 8, 10.

## Software layout

```
apps/pizero2w/     Docker stack (dump1090, gpsd, Flask API)
apps/esp32/        Feather firmware (ESP-IDF, planned)
```

## Pi Zero for testing

1. Flash **Raspberry Pi OS Lite (64-bit)** via Raspberry Pi Imager (SSH + WiFi in advanced options).
2. On the Pi: run `apps/pizero2w/setup.sh` or install Docker manually.
3. On your machine: `just build-pizero` (cross-build ARM64, loads locally). `just push-pizero` when ready for GHCR.
4. Dev without SDR: `just run-pizero-fake` — API on port 80 with `FAKE_SIGNALS=1`.

ESP32 can point at `http://<pi-ip>/api/latest` once the hotspot and container are up.

## API

- `GET /api/latest` - current signal for the handheld UI
- `GET /api/history` - last 100 logged signals
- `GET /api/health` - status
