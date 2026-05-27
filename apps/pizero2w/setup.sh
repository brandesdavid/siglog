#!/bin/bash
set -e
echo "=== SIGLOG Pi Zero Setup ==="

echo "[1/5] Installing Docker..."
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"

echo "[2/5] Blacklisting RTL-SDR kernel modules..."
sudo tee /etc/modprobe.d/rtlsdr.conf > /dev/null << 'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF
sudo rmmod dvb_usb_rtl28xxu 2>/dev/null || true

echo "[3/5] Enabling UART for GPS..."
if ! grep -q "enable_uart=1" /boot/firmware/config.txt 2>/dev/null; then
    echo "enable_uart=1" | sudo tee -a /boot/firmware/config.txt
fi
sudo raspi-config nonint do_serial_hw 0
sudo raspi-config nonint do_serial_cons 1

echo "[4/5] WiFi hotspot..."
sudo nmcli device wifi hotspot \
    ssid "siglog-pi" \
    password "siglog123" \
    ifname wlan0
sudo nmcli connection modify "Hotspot" \
    connection.autoconnect yes \
    connection.autoconnect-priority 100

echo "[5/5] Starting SIGLOG container..."
mkdir -p ~/siglog && cd ~/siglog
curl -fsSL -o docker-compose.yml \
    https://raw.githubusercontent.com/brandesdavid/siglog/main/apps/pizero2w/docker-compose.yml
docker compose pull
docker compose up -d

echo ""
echo "SIGLOG is running"
echo "   API:    http://$(hostname -I | awk '{print $1}')/api/latest"
echo "   Health: http://$(hostname -I | awk '{print $1}')/api/health"
echo ""
echo "Reboot recommended for UART changes: sudo reboot"
