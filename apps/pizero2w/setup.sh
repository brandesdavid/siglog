#!/bin/bash
set -euo pipefail

echo "=== SIGLOG Pi Zero Setup ==="

echo "[1/6] Installing Docker..."
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"

echo "[2/6] Blacklisting RTL-SDR kernel modules..."
sudo tee /etc/modprobe.d/rtlsdr.conf > /dev/null << 'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF
sudo rmmod dvb_usb_rtl28xxu 2>/dev/null || true

echo "[3/6] RTL-SDR USB permissions..."
sudo curl -fsSL -o /etc/udev/rules.d/20-rtlsdr.rules \
  https://raw.githubusercontent.com/osmocom/rtl-sdr/master/rtl-sdr.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG plugdev "$USER" 2>/dev/null || true

echo "[4/6] Enabling UART for GPS..."
if ! grep -q "enable_uart=1" /boot/firmware/config.txt 2>/dev/null; then
    echo "enable_uart=1" | sudo tee -a /boot/firmware/config.txt
fi
sudo raspi-config nonint do_serial_hw 0
sudo raspi-config nonint do_serial_cons 1

echo "[5/6] WiFi (auto: home first, hotspot fallback)..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p ~/siglog/scripts ~/siglog/control
cp -f "$SCRIPT_DIR/scripts/siglog-net" ~/siglog/scripts/
cp -f "$SCRIPT_DIR/scripts/host-control-watcher.sh" ~/siglog/scripts/
cp -f "$SCRIPT_DIR/scripts/siglog-host-control.service" ~/siglog/scripts/ 2>/dev/null || true
cp -f "$SCRIPT_DIR/scripts/pizero-hotspot-on.sh" ~/siglog/scripts/ 2>/dev/null || true
cp -f "$SCRIPT_DIR/scripts/pizero-hotspot-off.sh" ~/siglog/scripts/ 2>/dev/null || true
chmod +x ~/siglog/scripts/*
sudo ln -sf ~/siglog/scripts/siglog-net /usr/local/bin/siglog-net
bash ~/siglog/scripts/siglog-net auto
if [ -f ~/siglog/scripts/siglog-host-control.service ]; then
  sudo sed "s|/home/pi|$HOME|g" ~/siglog/scripts/siglog-host-control.service | \
    sudo tee /etc/systemd/system/siglog-host-control.service > /dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now siglog-host-control.service 2>/dev/null || true
fi

echo "[6/6] Starting SIGLOG container (pre-built image, no compile on Pi)..."
mkdir -p ~/siglog
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[[ -f "$REPO_ROOT/justfile" ]] && cp -f "$REPO_ROOT/justfile" ~/siglog/justfile
cp -f "$(dirname "$0")/docker-compose.yml" ~/siglog/docker-compose.yml 2>/dev/null || \
  curl -fsSL -o ~/siglog/docker-compose.yml \
    https://raw.githubusercontent.com/brandesdavid/siglog/main/apps/pizero2w/docker-compose.yml
cd ~/siglog
docker compose pull
if ! docker image inspect ghcr.io/brandesdavid/siglog-pi:latest >/dev/null 2>&1; then
    echo "ERROR: Image pull failed. Do not run 'docker compose build' on the Pi."
    echo "On your PC: just push-pizero   then run this setup again."
    exit 1
fi
docker compose up -d --no-build

echo ""
echo "SIGLOG is running"
LAN_IP="$(hostname -I | awk '{print $1}')"
echo "   API:    http://${LAN_IP}/api/latest"
echo "   Health: http://${LAN_IP}/api/health"
echo ""
echo "Reboot recommended for UART/USB group: sudo reboot"
echo "WiFi:  siglog-net status   (auto mode — no manual hotspot toggle needed)"
