# SIGLOG

Portable signal collector: RTL-SDR + GPS on a Raspberry Pi Zero 2W, live UI on an Adafruit ESP32-S3 Reverse TFT Feather, planning map on your laptop.

## Hardware

| Part | Role |
|------|------|
| Raspberry Pi Zero 2W | ADS-B, satellite scheduler, API, SQLite log |
| RTL-SDR R820T2 TCXO + dipole kit | 1090 MHz ADS-B; ~137 MHz Meteor LRPT |
| u-blox NEO-6M TTL | Geo-tag catches (optional until wired) |
| Micro USB OTG adapter | RTL-SDR on the Pi USB OTG port |
| ESP32-S3 Reverse TFT Feather | 240×135 display, WiFi client (planned) |
| LiPo + TP4056 | Pi + SDR power |

Pi and Feather talk over WiFi only. GPS: pins 1, 6, 8, 10 on the Pi.

## Software layout

```
apps/pizero2w/     Docker: dump1090, scheduler, Flask API, Pi-Log-UI
apps/laptop/       Planungskarte (nur Mac/Laptop, vor dem Rausgehen)
apps/esp32/        Feather firmware (planned)
```

---

## Was jetzt funktioniert

| Feature | Status | Hinweis |
|---------|--------|---------|
| **ADS-B** Flugzeuge | ✅ | `dump1090-fa`, live in `/api/latest` |
| **SQLite Log** | ✅ | Rarität, History, Geo wenn GPS da |
| **Flask API** | ✅ | Port 80 im Container |
| **Satelliten-Vorhersage** | ✅ | Meteor-M 2 / M2-3 / M2-4 (TLE) |
| **`/api/passes`** | ✅ | Nächste Überflüge, Countdown |
| **Laptop Planungskarte** | ✅ | `just laptop-map` — lädt `/api/map` vom Pi zuhause |
| **Pi Log-UI** | ✅ | `http://<pi-ip>/` — offline, gesammelte Daten |
| **WiFi `siglog-net`** | ✅ | Zuhause Router, draußen Hotspot (auto) |
| **Docker auf Pi** | ✅ | Nur `pull`, nie `build` auf dem Zero |
| **NOAA 15/18/19 APT** | ❌ | 2025 stillgelegt, nicht mehr im TLE |
| **Meteor LRPT Bilder** | ⏳ | Pass-Vorhersage ja, Auto-Decode nein |
| **APRS** | ⏳ | Noch nicht implementiert |
| **AIS** | ⏳ | Noch nicht implementiert |
| **ESP32 Display** | ⏳ | Pollt `/api/latest` (Firmware fehlt) |
| **Cloud Weltkarte** | ⏳ | Sync zu Arasaka/Coolify geplant |
| **Achievements** | ⏳ | Schema/API offen |

Ein RTL-SDR = eine Frequenz zur Zeit. Der Scheduler stoppt ADS-B nur für geplantes NOAA-APT (derzeit ohne Ziel-Satelliten). Meteor-Pässe werden angezeigt, aber nicht automatisch aufgenommen.

---

## Was noch gebaut werden muss

1. **ESP32 Firmware** — TFT, WiFi, `/api/latest`, Raritäts-Flash  
2. **Meteor LRPT Decode** — z.B. SatDump oder rtl_fm + Decoder; WAV → Bild  
3. **APRS** — `direwolf` auf 144.8 MHz, Zeitfenster neben ADS-B  
4. **GPS am Pi** — `SIGLOG_GPS=1 just update-on-pi` wenn NEO-6M dran  
5. **Push zur Cloud** — Hono/Bun/SQLite Dashboard, Karte aller Reisen  
6. **Achievements** — Regeln aus deiner SIGLOG-Spec  
7. **APRS/AIS Scheduler** — ein Dongle, mehrere Modi per Zeitplan  

---

## Pi Zero Setup

1. Flash **Raspberry Pi OS Lite 64-bit** (Imager: SSH + Heim-WLAN).  
2. **Mac:** `just push-pizero` nach Code-Änderungen.  
3. **Pi (frisch / Pi verloren — empfohlen):**

```bash
curl -fsSL https://raw.githubusercontent.com/brandesdavid/siglog/main/apps/pizero2w/install.sh | bash
nano ~/siglog/install.conf    # Hotspot-Passwort + Lat/Lng
siglog-pi install
sudo reboot
```

4. **Pi (Update):** `siglog-pi docker` oder `cd ~/siglog && just update-on-pi`  
5. **GPS optional:** `SIGLOG_GPS=1` in `~/siglog/install.conf`, dann `siglog-pi docker`  

**Wartung auf dem Pi:** `siglog-pi help` — einzelne Schritte (WiFi, RTL, Container, dedupe, …).

| Command | Where | What |
|---------|-------|------|
| `curl …/install.sh \| bash` | Pi | Erstinstallation (ohne git clone) |
| `siglog-pi install` | Pi | Volles Setup nach `install.conf` |
| `siglog-pi docker` | Pi | Image pull + Neustart |
| `siglog-pi wifi-auto` | Pi | Heim-WLAN + Hotspot-Fallback |
| `siglog-pi hotspot-secret` | Pi | SSID/Passwort aus `install.conf` anwenden |
| `just push-pizero` | Mac | ARM64 Image → GHCR |
| `just update-on-pi` | Pi | `pull` + `up --no-build` |
| `just setup-on-pi` | Pi | Wie `install.sh` (aus git clone) |

**Nicht auf dem Pi:** `docker compose build`, `git clone && make` für dump1090.

Position ohne GPS: `SIGLOG_LAT` / `SIGLOG_LON` in `docker-compose.yml` (Default Berlin).

---

## Laptop Planungskarte (vor dem Rausgehen)

Läuft **nicht** auf dem Pi. **Kein Pi nötig** — es gibt keine separate „Meteor-API“; Laptop und Pi nutzen dieselben **Celestrak-TLE** (Wetter-Satelliten-Gruppe) und berechnen Meteor-M-Pässe lokal.

```bash
just laptop-map
```

Browser: http://127.0.0.1:8765/

1. Breite/Länge eintragen (oder **Standort**) → **Pässe berechnen**  
2. Optional **Offline speichern** im Browser  
3. **Nichts vom Laptop auf den Pi kopieren** — Planung ist unabhängig vom Zero  

Der Pi braucht nur sein Docker-Image für ADS-B-Logging unterwegs (`just update-on-pi`). TLE-Cache auf dem Pi ist nur für den Scheduler dort, nicht für deine Laptop-Planung.

## Pi Log-UI (unterwegs, ohne Internet)

Am Pi-Hotspot oder Heim-WLAN — nur lokale API, keine CDN:

```
http://192.168.4.1/
```

oder Pi-IP aus `hostname -I`.

- Gesamtanzahl Fänge, GPS-getaggt  
- Live ADS-B (`/api/latest`)  
- Raritäts-Balken  
- Tabelle der letzten Fänge  

Nach Code-Änderung: `just push-pizero` → Pi `just update-on-pi`.

---

## API

| Endpoint | Beschreibung |
|----------|----------------|
| `GET /` | Pi Log-UI (offline) |
| `GET /api/stats` | Zähler, Rarität, Typen |
| `GET /api/map` | Pässe + Bodenspur (für Laptop) |
| `GET /api/latest` | Aktuelles Signal für ESP32 |
| `GET /api/passes` | Nächste Meteor-Pässe (JSON) |
| `GET /api/history` | Letzte 100 Signale |
| `GET /api/health` | Status |

---

## Rechtliches Kurz

Nur **legale passive** Signale: ADS-B, Amateurfunk wo erlaubt, Wetter-Satelliten. **Kein** Behördenfunk — in DE digital und verschlüsselt.
