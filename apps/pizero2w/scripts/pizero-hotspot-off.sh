#!/bin/bash
set -euo pipefail

if nmcli -t -f NAME connection show | grep -qx Hotspot; then
  sudo nmcli connection down Hotspot 2>/dev/null || true
  echo "Hotspot stopped. Pi should reconnect to saved home WiFi on its own."
else
  echo "No Hotspot connection profile found."
fi
