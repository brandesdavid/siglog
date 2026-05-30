#!/bin/bash
set -euo pipefail

HOTSPOT_SSID="${SIGLOG_HOTSPOT_SSID:-siglog-pi}"
HOTSPOT_PASSWORD="${SIGLOG_HOTSPOT_PASSWORD:-siglog123}"

if nmcli -t -f NAME connection show | grep -qx Hotspot; then
  sudo nmcli connection up Hotspot
else
  sudo nmcli device wifi hotspot \
    ssid "$HOTSPOT_SSID" \
    password "$HOTSPOT_PASSWORD" \
    ifname wlan0
  sudo nmcli connection modify Hotspot \
    connection.autoconnect yes \
    connection.autoconnect-priority 50
fi

echo "Hotspot active. Connect phone to: $HOTSPOT_SSID"
echo "API: http://192.168.4.1/api/latest  (or: http://$(hostname -I | awk '{print $1}')/api/latest)"
