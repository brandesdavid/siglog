#!/bin/sh
set -e
mkdir -p /app/data/dump1090
if [ "$FAKE_SIGNALS" = "1" ]; then
  exec python3 /app/api/server.py
fi
GPS_DEVICE="${GPS_DEVICE:-/dev/ttyAMA0}"
if [ -e "$GPS_DEVICE" ]; then
  SUPERVISOR_CONF=/etc/supervisor/conf.d/siglog.conf
else
  SUPERVISOR_CONF=/etc/supervisor/conf.d/siglog-no-gps.conf
fi
exec /usr/bin/supervisord -n -c "$SUPERVISOR_CONF"
