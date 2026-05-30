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
apps/pizero2w/     Docker: dump1090, scheduler, Flask API, Pi Log-UI
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
| **Pi Log-UI** | ✅ | Log · Plan · Focus + **Controls** (Header) |
| **Hex-Decode** | ✅ | adsbdb.com, Ergebnis in SQLite (überlebt Reboot) |
| **Raritäts-Tiers** | ✅ | Live + nach Decode; Hex-only zunächst COMMON |
| **Satelliten-Vorhersage** | ✅ | Meteor-M 2 / M2-3 / M2-4 (TLE) |
| **Plan-Cache auf Pi** | ✅ | `/api/plan` offline; Fetch speichert auf SD |
| **Focus + Record** | ✅ | Countdown, Kompass, LRPT-Aufnahme pro Pass |
| **Meteor-Logging** | ✅ | Manuelle Captures → SQLite (`METEOR` Typ) |
| **WiFi `siglog-net`** | ✅ | Zuhause Router, draußen Hotspot (auto) |
| **Host Controls** | ✅ | WiFi/Hotspot aus Web-UI (`siglog-host-control`) |
| **SDR Capture** | ✅ | LRPT/APT raw WAV; Stop/Restart ADS-B |
| **Install-Skripte** | ✅ | `install.sh`, `setup.sh`, `siglog-pi`, `install.conf` |
| **Laptop Planungskarte** | ✅ | `just laptop-map` — Celestrak lokal |
| **Docker auf Pi** | ✅ | Nur `pull`, nie `build` auf dem Zero |
| **NOAA 15/18/19 APT** | ❌ | 2025 stillgelegt, nicht mehr im TLE |
| **Meteor LRPT Decode** | ⏳ | Pass + Record ja; Auto-Decode auf Pi nein |
| **APRS** | ⏳ | Noch nicht implementiert |
| **AIS** | ⏳ | Noch nicht implementiert |
| **ESP32 Display** | ⏳ | Pollt `/api/latest` (Firmware fehlt) |
| **Cloud Weltkarte** | ⏳ | Sync zu Arasaka/Coolify geplant |
| **Achievements** | ⏳ | Schema/API offen |

Ein RTL-SDR = eine Frequenz zur Zeit. Der Scheduler stoppt ADS-B nur für geplantes NOAA-APT (derzeit ohne Ziel-Satelliten). Meteor-Pässe werden geplant und manuell aus Focus/Controls aufgenommen; Decode zuhause (z.B. SatDump).

---

## Was noch gebaut werden muss

1. **ESP32 Firmware** — TFT, WiFi, `/api/latest`, Raritäts-Flash  
2. **Meteor LRPT Decode** — z.B. SatDump oder rtl_fm + Decoder; WAV → Bild  
3. **APRS** — `direwolf` auf 144.8 MHz, Zeitfenster neben ADS-B  
4. **GPS am Pi** — `SIGLOG_GPS=1` in `install.conf`, dann `siglog-pi docker`  
5. **Push zur Cloud** — Hono/Bun/SQLite Dashboard, Karte aller Reisen  
6. **Achievements** — Regeln aus deiner SIGLOG-Spec  
7. **APRS/AIS Scheduler** — ein Dongle, mehrere Modi per Zeitplan  

---

## Pi Zero Setup

### Erstinstallation

1. Flash **Raspberry Pi OS Lite 64-bit** (Imager: SSH + Heim-WLAN).  
2. **Pi (frisch / clean canvas — empfohlen):**

```bash
curl -fsSL https://raw.githubusercontent.com/brandesdavid/siglog/main/apps/pizero2w/install.sh | bash
nano ~/siglog/install.conf    # Hotspot-Passwort, Lat/Lng, optional GPS
siglog-pi install
sudo reboot
```

3. **Alternativ aus git clone auf dem Pi:**

```bash
cd ~/siglog && just setup-on-pi
# oder: bash apps/pizero2w/setup.sh
```

`setup.sh` ist ein dünner Wrapper → ruft `install.sh` im gleichen Ordner auf (lokal oder per curl).

### Konfiguration (`~/siglog/install.conf`)

Kopie von `install.conf.example`:

| Variable | Bedeutung |
|----------|-----------|
| `SIGLOG_HOTSPOT_SSID` | Hotspot-Name unterwegs (Default `siglog-pi`) |
| `SIGLOG_HOTSPOT_PASSWORD` | Hotspot-Passwort (min. 8 Zeichen) |
| `SIGLOG_LAT` / `SIGLOG_LON` | Standort ohne GPS |
| `SIGLOG_GPS` | `1` = NEO-6M an UART |
| `GITHUB_REPO` / `GITHUB_BRANCH` | Quelle für Script-Sync |

Nach Änderungen: `siglog-pi hotspot-secret` (Passwort) oder `siglog-pi docker` (GPS/Compose).

### Updates & Wartung

| Command | Where | What |
|---------|-------|------|
| `curl …/install.sh \| bash` | Pi | Erstinstallation (ohne git clone) |
| `bash setup.sh` / `just setup-on-pi` | Pi | Install aus lokalem Repo |
| `siglog-pi install` | Pi | Volles Setup nach `install.conf` |
| `siglog-pi docker` | Pi | Image pull + Neustart |
| `siglog-pi wifi-auto` | Pi | Heim-WLAN + Hotspot-Fallback |
| `siglog-pi wifi-status` | Pi | Modus + URLs |
| `siglog-pi hotspot-secret` | Pi | SSID/Passwort aus `install.conf` |
| `siglog-pi host-control` | Pi | Web-UI WiFi-Buttons aktivieren |
| `siglog-pi dedupe` | Pi | ADS-B-Duplikate (30-Min-Fenster) |
| `siglog-pi logs [svc]` | Pi | Container-Logs (api, dump1090, …) |
| `just push-pizero` | Mac | ARM64 Image → GHCR |
| `just update-on-pi` | Pi | Scripts sync + `pull` + `up --no-build` |

**Mac nach Code-Änderung:** `just push-pizero` → auf dem Pi `just update-on-pi`.

**Nicht auf dem Pi:** `docker compose build`, `git clone && make` für dump1090.

### WiFi unterwegs

- Hotspot: **`http://192.168.4.1/`** (Phone/Laptop am Pi-Hotspot)
- Zuhause: `http://<pi-ip>/` (`hostname -I`)
- Auto: `siglog-pi wifi-auto` — Heim-WLAN bevorzugt, sonst Hotspot
- Passwort ändern: `install.conf` → `siglog-pi hotspot-secret`

Position ohne GPS: `SIGLOG_LAT` / `SIGLOG_LON` in `install.conf` oder `docker-compose.yml`.

---

## Pi Log-UI (unterwegs, ohne Internet)

```
http://192.168.4.1/
```

oder Pi-IP aus `hostname -I`. Alles lokal — keine CDN, SQLite auf der SD-Karte.

### Header

- **SIGLOG** + aktueller Modus (ADS-B / WiFi / GPS)
- **Controls** (rechts) — öffnet Einstellungsseite; **← Log** kehrt zurück

### Haupt-Tabs

| Tab | Inhalt |
|-----|--------|
| **Log** | Stats, Live ADS-B, Raritäts-Balken, History (Callsign / Hex-only) |
| **Plan** | Meteor-Pässe, Karte, Fetch (speichert Plan auf Pi für offline) |
| **Focus** | Ein Pass: Countdown, Blickrichtung, Mini-Karte, **Record** |

**Hex-Tab:** Mode-S ohne Callsign → zunächst **COMMON**. Button **Decode hex** (braucht Heim-WLAN / adsbdb.com). Nach Decode wird Rarität neu berechnet und in SQLite gespeichert.

### Controls (Header-Button)

Drei Unter-Tabs — kein Scrollen mehr durch die Log-Seite:

| Unter-Tab | Inhalt |
|-----------|--------|
| **Controls** | LRPT/APT-Aufnahme, Stop, ADS-B restart, WiFi/Hotspot, Modus-Pills, Capture-Liste |
| **Tiers** | Legende: LEGEND → COMMON (ADS-B live, nach Decode, Satelliten) |
| **Console** | Live-Status nach Control-Aktionen + Service-Logs (API, dump1090, …) |

Nach Klick auf Capture/WiFi/Record wechselt die UI automatisch zur **Console**, damit du sofort Feedback siehst.

JSON-Export: Link unten auf dem Log-Tab → `/api/export`.

---

## Rarität (Kurzüberblick)

Details in der UI unter **Controls → Tiers**. Logik in `apps/pizero2w/api/rarity.py`.

| Tier | ADS-B live | Nach Hex-Decode / Satellit |
|------|------------|----------------------------|
| **LEGEND** | Notfall-Squawks, Intercept 7777 | Concorde, An-225, Stargazer N140SC |
| **EPIC** | Callsign ohne Hex, Military-Prefixes, NATO/MAGIC | Militär-Typen (E-3, B-52, P-8, …), USA-xxx |
| **RARE** | — | A380, Beluga, IL-76, Warbirds, Regierung/Polizei |
| **UNCOMMON** | — | GA, Business Jets, Meteor LRPT-Logs |
| **COMMON** | Hex-only vor Decode, normale Airline | Lufthansa, Ryanair, …; NOAA APT |

---

## Laptop Planungskarte (vor dem Rausgehen)

Läuft **nicht** auf dem Pi. Kein Pi nötig — Laptop und Pi nutzen dieselben **Celestrak-TLE** (Wetter-Satelliten-Gruppe).

```bash
just laptop-map
```

Browser: http://127.0.0.1:8765/

1. Breite/Länge eintragen (oder **Standort**) → **Pässe berechnen**  
2. Optional **Offline speichern** im Browser  
3. **Unabhängig vom Pi** — der Pi kann seinen Plan separat fetchen (`Plan → Fetch` in der Log-UI)

---

## API

| Endpoint | Beschreibung |
|----------|----------------|
| `GET /` | Pi Log-UI |
| `GET /api/stats` | Zähler, Rarität, Typen |
| `GET /api/history` | Paginierte History (`?tab=ident\|hex`) |
| `GET /api/latest` | Aktuelles Signal (ESP32) |
| `GET /api/map` | Pässe + Bodenspur (Laptop) |
| `GET /api/plan` | Gecachter Plan vom Pi (offline) |
| `POST /api/plan/fetch` | TLE holen + auf Pi speichern |
| `GET /api/passes` | Nächste Meteor-Pässe (JSON) |
| `POST /api/decode` | Hex-Zeilen decodieren + Rarität updaten |
| `GET /api/export` | SQLite als JSON |
| `GET /api/health` | Status |
| `GET /api/control/status` | Capture-Modus, WiFi-Modus, GPS |
| `POST /api/control/capture` | LRPT/APT oder `{ passIndex }` für Focus |
| `POST /api/control/stop` | Aufnahme stoppen |
| `POST /api/control/restart` | z.B. dump1090 |
| `POST /api/control/host` | WiFi/Hotspot (`status`, `hotspot`, `wifi`, `auto`) |
| `GET /api/logs?service=` | Container-Logs für Console-Tab |
| `GET /api/captures/<name>` | WAV-Datei download |

---

## Rechtliches Kurz

Nur **legale passive** Signale: ADS-B, Amateurfunk wo erlaubt, Wetter-Satelliten. **Kein** Behördenfunk — in DE digital und verschlüsselt.
