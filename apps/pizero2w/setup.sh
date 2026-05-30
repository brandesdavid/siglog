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

echo "[5/6] WiFi (home network stays default; no hotspot here)..."
if nmcli -t -f NAME connection show | grep -qx Hotspot; then
  sudo nmcli connection modify Hotspot \
    connection.autoconnect yes \
    connection.autoconnect-priority 50
  sudo nmcli connection down Hotspot 2>/dev/null || true
  echo "    Existing Hotspot profile set to low priority (50) and stopped."
  echo "    Draußen: bash ~/siglog/scripts/pizero-hotspot-on.sh"
fi
echo "    Tip: set home WiFi priority 200 once (if not from Imager):"
echo "    sudo nmcli connection modify \"DEIN_WLAN\" connection.autoconnect-priority 200"

if [ "${SIGLOG_ENABLE_HOTSPOT:-0}" = "1" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  bash "$SCRIPT_DIR/scripts/pizero-hotspot-on.sh"
fi

echo "[6/6] Starting SIGLOG container (pre-built image, no compile on Pi)..."
mkdir -p ~/siglog
cp -f "$(dirname "$0")/docker-compose.yml" ~/siglog/docker-compose.yml 2>/dev/null || \
  curl -fsSL -o ~/siglog/docker-compose.yml \
    https://raw.githubusercontent.com/brandesdavid/siglog/main/apps/pizero2w/docker-compose.yml
mkdir -p ~/siglog/scripts
cp -f "$(dirname "$0")/scripts/pizero-hotspot-on.sh" ~/siglog/scripts/ 2>/dev/null || true
cp -f "$(dirname "$0")/scripts/pizero-hotspot-off.sh" ~/siglog/scripts/ 2>/dev/null || true
chmod +x ~/siglog/scripts/*.sh 2>/dev/null || true
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
echo "Outdoor hotspot (manual): ~/siglog/scripts/pizero-hotspot-on.sh"
echo "Stop hotspot:             ~/siglog/scripts/pizero-hotspot-off.sh"
