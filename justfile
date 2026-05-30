default:
    @just --list

# --- Mac (never build on the Pi) ---

build-pizero:
    DOCKER_BUILDKIT=1 docker buildx build --platform linux/arm64 -f apps/pizero2w/Dockerfile -t ghcr.io/brandesdavid/siglog-pi:latest --load apps/pizero2w

push-pizero:
    DOCKER_BUILDKIT=1 docker buildx build --platform linux/arm64 -f apps/pizero2w/Dockerfile -t ghcr.io/brandesdavid/siglog-pi:latest --push apps/pizero2w

release-pizero: push-pizero
    @echo "Image pushed. On the Pi run:  just update-on-pi"

run-pizero-fake:
    cd apps/pizero2w && docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

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
    mkdir -p "$PI_DIR/scripts"
    if [[ -f apps/pizero2w/docker-compose.yml ]]; then
      echo "Using local apps/pizero2w/"
      cp -f apps/pizero2w/docker-compose.yml "$PI_DIR/"
      cp -f apps/pizero2w/docker-compose.gps.yml "$PI_DIR/"
      cp -f apps/pizero2w/scripts/siglog-net "$PI_DIR/scripts/"
      chmod +x "$PI_DIR/scripts/"*
      [[ -f justfile ]] && cp -f justfile "$PI_DIR/justfile"
    else
      echo "Fetching from GitHub main..."
      curl -fsSL -o "$PI_DIR/docker-compose.yml" "$REPO_RAW/docker-compose.yml"
      curl -fsSL -o "$PI_DIR/docker-compose.gps.yml" "$REPO_RAW/docker-compose.gps.yml"
      curl -fsSL -o "$PI_DIR/scripts/siglog-net" "$REPO_RAW/scripts/siglog-net"
      curl -fsSL -o "$PI_DIR/justfile" "https://raw.githubusercontent.com/brandesdavid/siglog/main/justfile"
      chmod +x "$PI_DIR/scripts/siglog-net"
    fi
    if [[ ! -x /usr/local/bin/siglog-net ]]; then
      sudo ln -sf "$PI_DIR/scripts/siglog-net" /usr/local/bin/siglog-net
    fi
    cd "$PI_DIR"
    docker compose pull
    if ! docker image inspect ghcr.io/brandesdavid/siglog-pi:latest >/dev/null 2>&1; then
      echo "ERROR: pull failed. On Mac run:  just push-pizero"
      exit 1
    fi
    GPS_COMPOSE=""
    if [[ -f "$PI_DIR/docker-compose.gps.yml" ]] && { [[ -e /dev/serial0 ]] || [[ -e /dev/ttyAMA0 ]] || [[ -e /dev/ttyS0 ]]; }; then
      GPS_COMPOSE="-f docker-compose.gps.yml"
      echo "GPS serial found — enabling GPS compose overlay"
    else
      echo "No GPS serial device — running without GPS (ADS-B only)"
    fi
    docker compose $GPS_COMPOSE up -d --no-build
    IP="$(hostname -I | awk '{print $1}')"
    echo ""
    echo "SIGLOG updated."
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
