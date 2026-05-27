#!/bin/sh
set -e
mkdir -p /app/data/dump1090
if [ "$FAKE_SIGNALS" = "1" ]; then
  exec python3 /app/api/server.py
fi
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
