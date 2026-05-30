#!/bin/bash

siglog_repo_raw() {
  local repo="${GITHUB_REPO:-brandesdavid/siglog}"
  local branch="${GITHUB_BRANCH:-main}"
  echo "https://raw.githubusercontent.com/${repo}/${branch}/apps/pizero2w"
}

siglog_load_config() {
  SIGLOG_PI_DIR="${SIGLOG_PI_DIR:-$HOME/siglog}"
  mkdir -p "$SIGLOG_PI_DIR/scripts" "$SIGLOG_PI_DIR/control"
  if [[ -f "$SIGLOG_PI_DIR/install.conf" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$SIGLOG_PI_DIR/install.conf"
    set +a
  elif [[ -f "$SIGLOG_PI_DIR/install.conf.example" ]]; then
    cp "$SIGLOG_PI_DIR/install.conf.example" "$SIGLOG_PI_DIR/install.conf"
    set -a
    # shellcheck disable=SC1090
    source "$SIGLOG_PI_DIR/install.conf"
    set +a
    echo "Created $SIGLOG_PI_DIR/install.conf — edit hotspot password before going outside."
  fi
  SIGLOG_PI_DIR="${SIGLOG_PI_DIR:-$HOME/siglog}"
  export SIGLOG_HOTSPOT_SSID="${SIGLOG_HOTSPOT_SSID:-siglog-pi}"
  export SIGLOG_HOTSPOT_PASSWORD="${SIGLOG_HOTSPOT_PASSWORD:-siglog123}"
  export SIGLOG_HOME_PRIO="${SIGLOG_HOME_PRIO:-200}"
  export SIGLOG_HOTSPOT_PRIO="${SIGLOG_HOTSPOT_PRIO:-50}"
  export SIGLOG_LAT="${SIGLOG_LAT:-52.52}"
  export SIGLOG_LON="${SIGLOG_LON:-13.405}"
  export SIGLOG_GPS="${SIGLOG_GPS:-0}"
  export SIGLOG_CONTROL_DIR="$SIGLOG_PI_DIR/control"
}

siglog_write_env_files() {
  cat > "$SIGLOG_PI_DIR/.env" <<EOF
SIGLOG_CONTROL_DIR=${SIGLOG_CONTROL_DIR}
SIGLOG_LAT=${SIGLOG_LAT}
SIGLOG_LON=${SIGLOG_LON}
EOF
  local marker="# siglog hotspot"
  if ! grep -q "$marker" "$HOME/.bashrc" 2>/dev/null; then
    cat >> "$HOME/.bashrc" <<EOF

$marker
export SIGLOG_HOTSPOT_SSID="${SIGLOG_HOTSPOT_SSID}"
export SIGLOG_HOTSPOT_PASSWORD="${SIGLOG_HOTSPOT_PASSWORD}"
export SIGLOG_HOME_PRIO="${SIGLOG_HOME_PRIO}"
export SIGLOG_HOTSPOT_PRIO="${SIGLOG_HOTSPOT_PRIO}"
EOF
  fi
}

siglog_fetch_asset() {
  local rel="$1"
  local dest="$2"
  if [[ -n "${SIGLOG_INSTALL_LOCAL:-}" ]] && [[ -f "${SIGLOG_INSTALL_LOCAL}/${rel}" ]]; then
    cp -f "${SIGLOG_INSTALL_LOCAL}/${rel}" "$dest"
    return 0
  fi
  curl -fsSL -o "$dest" "$(siglog_repo_raw)/${rel#apps/pizero2w/}"
}

siglog_sync_scripts() {
  siglog_load_config
  local scripts=(
    "scripts/siglog-net"
    "scripts/host-control-watcher.sh"
    "scripts/siglog-host-control.service"
    "scripts/pizero-hotspot-on.sh"
    "scripts/pizero-hotspot-off.sh"
    "scripts/siglog-pi"
    "scripts/dedupe-signals.sh"
    "docker-compose.yml"
    "docker-compose.gps.yml"
  )
  for rel in "${scripts[@]}"; do
    local base
    base="$(basename "$rel")"
    if [[ "$rel" == scripts/* ]]; then
      siglog_fetch_asset "$rel" "$SIGLOG_PI_DIR/scripts/$base"
    else
      siglog_fetch_asset "$rel" "$SIGLOG_PI_DIR/$base"
    fi
  done
  chmod +x "$SIGLOG_PI_DIR/scripts/"* 2>/dev/null || true
  sudo ln -sf "$SIGLOG_PI_DIR/scripts/siglog-net" /usr/local/bin/siglog-net
  sudo ln -sf "$SIGLOG_PI_DIR/scripts/siglog-pi" /usr/local/bin/siglog-pi
  curl -fsSL -o "$SIGLOG_PI_DIR/justfile" \
    "https://raw.githubusercontent.com/${GITHUB_REPO:-brandesdavid/siglog}/${GITHUB_BRANCH:-main}/justfile" \
    2>/dev/null || true
}

siglog_install_docker() {
  if command -v docker >/dev/null 2>&1; then
    echo "Docker already installed."
    return 0
  fi
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
}

siglog_install_rtlsdr() {
  sudo tee /etc/modprobe.d/rtlsdr.conf > /dev/null <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF
  sudo rmmod dvb_usb_rtl28xxu 2>/dev/null || true
  sudo curl -fsSL -o /etc/udev/rules.d/20-rtlsdr.rules \
    https://raw.githubusercontent.com/osmocom/rtl-sdr/master/rtl-sdr.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger
  sudo usermod -aG plugdev "$USER" 2>/dev/null || true
}

siglog_install_gps_uart() {
  if [[ -f /boot/firmware/config.txt ]] && ! grep -q "enable_uart=1" /boot/firmware/config.txt 2>/dev/null; then
    echo "enable_uart=1" | sudo tee -a /boot/firmware/config.txt
  fi
  if command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_serial_hw 0
    sudo raspi-config nonint do_serial_cons 1
  fi
}

siglog_apply_hotspot_secrets() {
  siglog_load_config
  export SIGLOG_HOTSPOT_SSID SIGLOG_HOTSPOT_PASSWORD SIGLOG_HOME_PRIO SIGLOG_HOTSPOT_PRIO
  if nmcli -t -f NAME connection show 2>/dev/null | grep -qx Hotspot; then
    sudo nmcli connection modify Hotspot \
      wifi.ssid "$SIGLOG_HOTSPOT_SSID" \
      wifi-sec.psk "$SIGLOG_HOTSPOT_PASSWORD" 2>/dev/null || true
  fi
}

siglog_install_wifi() {
  siglog_load_config
  siglog_sync_scripts
  siglog_write_env_files
  export SIGLOG_HOTSPOT_SSID SIGLOG_HOTSPOT_PASSWORD SIGLOG_HOME_PRIO SIGLOG_HOTSPOT_PRIO
  bash "$SIGLOG_PI_DIR/scripts/siglog-net" auto
  siglog_apply_hotspot_secrets
}

siglog_install_host_control() {
  siglog_load_config
  if [[ ! -f "$SIGLOG_PI_DIR/scripts/siglog-host-control.service" ]]; then
    echo "host-control service file missing"
    return 1
  fi
  sudo sed "s|/home/pi|$HOME|g" "$SIGLOG_PI_DIR/scripts/siglog-host-control.service" | \
    sudo tee /etc/systemd/system/siglog-host-control.service > /dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now siglog-host-control.service
}

siglog_docker_update() {
  siglog_load_config
  cd "$SIGLOG_PI_DIR"
  set -a
  # shellcheck disable=SC1090
  source "$SIGLOG_PI_DIR/.env" 2>/dev/null || true
  set +a
  docker compose pull
  if ! docker image inspect ghcr.io/brandesdavid/siglog-pi:latest >/dev/null 2>&1; then
    echo "ERROR: image pull failed. On Mac run: just push-pizero"
    return 1
  fi
  if [[ "${SIGLOG_GPS}" == "1" ]] && [[ -f docker-compose.gps.yml ]]; then
    docker compose -f docker-compose.yml -f docker-compose.gps.yml up -d --no-build
  else
    docker compose -f docker-compose.yml up -d --no-build
  fi
}

siglog_install_container() {
  siglog_load_config
  siglog_write_env_files
  siglog_docker_update
}

siglog_full_install() {
  siglog_load_config
  if [[ ! -f "$SIGLOG_PI_DIR/install.conf" ]]; then
    if [[ -f "${SIGLOG_INSTALL_LOCAL:-}/install.conf.example" ]]; then
      cp "${SIGLOG_INSTALL_LOCAL}/install.conf.example" "$SIGLOG_PI_DIR/install.conf"
    else
      siglog_fetch_asset "install.conf.example" "$SIGLOG_PI_DIR/install.conf.example"
      cp "$SIGLOG_PI_DIR/install.conf.example" "$SIGLOG_PI_DIR/install.conf"
    fi
    echo "Edit $SIGLOG_PI_DIR/install.conf (hotspot password!) then run: siglog-pi install"
    return 1
  fi
  siglog_load_config
  echo "[1/7] Docker"
  siglog_install_docker
  echo "[2/7] RTL-SDR"
  siglog_install_rtlsdr
  echo "[3/7] GPS UART"
  siglog_install_gps_uart
  echo "[4/7] Scripts + compose"
  siglog_sync_scripts
  siglog_write_env_files
  echo "[5/7] WiFi auto + hotspot"
  siglog_install_wifi
  echo "[6/7] Host control (web UI WiFi buttons)"
  siglog_install_host_control
  echo "[7/7] SIGLOG container"
  siglog_install_container
  LAN_IP="$(hostname -I | awk '{print $1}')"
  echo ""
  echo "SIGLOG ready."
  echo "  UI:     http://${LAN_IP}/"
  echo "  API:    http://${LAN_IP}/api/latest"
  echo "  WiFi:   siglog-net status"
  echo "  Maint:  siglog-pi help"
  echo "Reboot recommended: sudo reboot"
}
