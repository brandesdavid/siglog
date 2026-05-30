default:
    @just --list

# --- Mac (never build on the Pi) ---

build-pizero:
    #!/usr/bin/env bash
    set -euo pipefail
    export DOCKER_BUILDKIT=1
    for n in 1 2 3; do
      echo "=== build-pizero attempt ${n}/3 ==="
      if docker buildx build --platform linux/arm64 \
        -f apps/pizero2w/Dockerfile \
        -t ghcr.io/brandesdavid/siglog-pi:latest \
        --load apps/pizero2w; then
        exit 0
      fi
      sleep 15
    done
    echo "Build failed after 3 attempts. Check Docker Desktop network / VPN, then retry."
    exit 1

push-pizero:
    #!/usr/bin/env bash
    set -euo pipefail
    export DOCKER_BUILDKIT=1
    for n in 1 2 3; do
      echo "=== push-pizero attempt ${n}/3 ==="
      if docker buildx build --platform linux/arm64 \
        -f apps/pizero2w/Dockerfile \
        -t ghcr.io/brandesdavid/siglog-pi:latest \
        --push apps/pizero2w; then
        exit 0
      fi
      sleep 15
    done
    echo "Push failed after 3 attempts. Check Docker Desktop network / VPN, then retry."
    exit 1

release-pizero: push-pizero
    @echo "Image pushed. On the Pi run:  just update-on-pi"

run-pizero-fake:
    cd apps/pizero2w && docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

laptop-map:
    @echo "http://127.0.0.1:8765/ — Breite/Länge, Pässe berechnen (Celestrak, kein Pi)"
    python3 -m http.server 8765 --directory apps/laptop

# --- Pi Zero (pull only — no docker compose build, no git clone && make) ---

# to let the Pi install just:
# sudo apt-get update && sudo apt-get install -y just

setup-on-pi:
    bash apps/pizero2w/setup.sh

update-on-pi:
    #!/usr/bin/env bash
    set -euo pipefail
    PI_DIR="${SIGLOG_PI_DIR:-$HOME/siglog}"
    REPO_RAW="https://raw.githubusercontent.com/brandesdavid/siglog/main/apps/pizero2w"
    mkdir -p "$PI_DIR/scripts" "$PI_DIR/control"
    if [[ -f apps/pizero2w/docker-compose.yml ]]; then
      echo "Using local apps/pizero2w/"
      cp -f apps/pizero2w/docker-compose.yml "$PI_DIR/"
      cp -f apps/pizero2w/docker-compose.gps.yml "$PI_DIR/"
      cp -f apps/pizero2w/scripts/siglog-net "$PI_DIR/scripts/"
      cp -f apps/pizero2w/scripts/siglog-pi "$PI_DIR/scripts/"
      cp -f apps/pizero2w/scripts/pi-bootstrap.sh "$PI_DIR/scripts/"
      cp -f apps/pizero2w/scripts/host-control-watcher.sh "$PI_DIR/scripts/"
      cp -f apps/pizero2w/scripts/siglog-host-control.service "$PI_DIR/scripts/" 2>/dev/null || true
      cp -f apps/pizero2w/install.conf.example "$PI_DIR/" 2>/dev/null || true
      chmod +x "$PI_DIR/scripts/"*
      [[ -f justfile ]] && cp -f justfile "$PI_DIR/justfile"
    else
      echo "Fetching from GitHub main..."
      curl -fsSL -o "$PI_DIR/docker-compose.yml" "$REPO_RAW/docker-compose.yml"
      curl -fsSL -o "$PI_DIR/docker-compose.gps.yml" "$REPO_RAW/docker-compose.gps.yml"
      curl -fsSL -o "$PI_DIR/scripts/siglog-net" "$REPO_RAW/scripts/siglog-net"
      curl -fsSL -o "$PI_DIR/scripts/siglog-pi" "$REPO_RAW/scripts/siglog-pi"
      curl -fsSL -o "$PI_DIR/scripts/pi-bootstrap.sh" "$REPO_RAW/scripts/pi-bootstrap.sh"
      curl -fsSL -o "$PI_DIR/scripts/host-control-watcher.sh" "$REPO_RAW/scripts/host-control-watcher.sh"
      curl -fsSL -o "$PI_DIR/install.conf.example" "$REPO_RAW/install.conf.example"
      curl -fsSL -o "$PI_DIR/justfile" "https://raw.githubusercontent.com/brandesdavid/siglog/main/justfile"
      chmod +x "$PI_DIR/scripts/siglog-net" "$PI_DIR/scripts/siglog-pi" "$PI_DIR/scripts/host-control-watcher.sh"
    fi
    if [[ ! -x /usr/local/bin/siglog-net ]]; then
      sudo ln -sf "$PI_DIR/scripts/siglog-net" /usr/local/bin/siglog-net
    fi
    if [[ ! -x /usr/local/bin/siglog-pi ]]; then
      sudo ln -sf "$PI_DIR/scripts/siglog-pi" /usr/local/bin/siglog-pi
    fi
    cd "$PI_DIR"
    export SIGLOG_CONTROL_DIR="$PI_DIR/control"
    docker compose pull
    if ! docker image inspect ghcr.io/brandesdavid/siglog-pi:latest >/dev/null 2>&1; then
      echo "ERROR: pull failed. On Mac run:  just push-pizero"
      exit 1
    fi
    if [[ "${SIGLOG_GPS:-0}" == "1" ]] && [[ -f docker-compose.gps.yml ]]; then
      echo "SIGLOG_GPS=1 — starting with GPS UART overlay"
      docker compose -f docker-compose.yml -f docker-compose.gps.yml up -d --no-build
    else
      echo "No GPS module (SIGLOG_GPS=0) — ADS-B + NOAA scheduler only"
      docker compose -f docker-compose.yml up -d --no-build
    fi
    IP="$(hostname -I | awk '{print $1}')"
    echo ""
    echo "SIGLOG updated."
    echo "  Log-UI: http://${IP}/"
    echo "  API:    http://${IP}/api/latest"
    echo "  Health: http://${IP}/api/health"
    echo "  WiFi:   siglog-net status"

net-auto:
    siglog-net auto

net-status:
    siglog-net status

net-hotspot:
    siglog-net hotspot

net-wifi:
    siglog-net wifi

dedupe-pi:
    docker exec siglog /app/scripts/dedupe-signals.sh /app/data/signals.db 30min

pull-siglog-export PI_URL="http://192.168.0.6":
    #!/usr/bin/env bash
    set -eu
    mkdir -p data/exports
    out="data/exports/siglog-$(date -u +%Y%m%dT%H%M%SZ).json"
    curl -fsSL "${PI_URL}/api/export" -o "$out"
    echo "Saved $out ($(wc -c < "$out" | tr -d ' ') bytes)"

push-siglog-export BRANCH="siglog-data":
    #!/usr/bin/env bash
    set -eu
    if ! git rev-parse --git-dir >/dev/null 2>&1; then
      echo "Not a git repo."
      exit 1
    fi
    if [[ -z "$(ls -A data/exports/*.json 2>/dev/null)" ]]; then
      echo "No data/exports/*.json — run: just pull-siglog-export"
      exit 1
    fi
    git fetch origin 2>/dev/null || true
    if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
      git checkout "${BRANCH}"
    else
      git checkout -b "${BRANCH}"
    fi
    git add data/exports/*.json
    if git diff --cached --quiet; then
      echo "Nothing new to commit."
      exit 0
    fi
    git commit -m "SIGLOG field export $(date -u +%Y-%m-%dT%H:%MZ)"
    git push -u origin "${BRANCH}"
    echo "Pushed branch ${BRANCH}"

sync-siglog-github PI_URL="http://192.168.0.6" BRANCH="siglog-data":
    PI_URL={{PI_URL}} BRANCH={{BRANCH}} just pull-siglog-export && just push-siglog-export 
