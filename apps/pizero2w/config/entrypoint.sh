#!/bin/sh
set -e
mkdir -p /app/data/dump1090 /app/data/logs /app/data/captures /app/data/control
if [ "$FAKE_SIGNALS" = "1" ]; then
  exec python3 /app/api/server.py
fi
GPS_DEVICE="${GPS_DEVICE:-/dev/ttyAMA0}"
if [ -e "$GPS_DEVICE" ]; then
  SUPERVISOR_CONF=/etc/supervisor/conf.d/siglog.conf
else
  SUPERVISOR_CONF=/etc/supervisor/conf.d/siglog-no-gps.conf
fi
export SUPERVISOR_CONFIG="$SUPERVISOR_CONF"
exec /usr/bin/supervisord -n -c "$SUPERVISOR_CONF"
