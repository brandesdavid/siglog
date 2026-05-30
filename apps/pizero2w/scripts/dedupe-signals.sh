#!/bin/sh
set -eu
DB="${1:-/app/data/signals.db}"
MODE="${2:-30min}"
if [ ! -f "$DB" ]; then
  echo "DB not found: $DB"
  exit 1
fi
python3 <<PY
import sqlite3
import sys

db = "$DB"
mode = "$MODE"
con = sqlite3.connect(db)
before = con.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

if mode == "callsign":
    con.execute(
        """
        DELETE FROM signals
        WHERE id NOT IN (SELECT MIN(id) FROM signals GROUP BY callsign)
        """
    )
elif mode == "30min":
    con.execute(
        """
        DELETE FROM signals
        WHERE id IN (
          SELECT id FROM (
            SELECT id,
              LAG(ts) OVER (
                PARTITION BY COALESCE(aircraft_key, callsign)
                ORDER BY ts
              ) AS prev_ts
            FROM signals
          )
          WHERE prev_ts IS NOT NULL AND ts - prev_ts < 1800
        )
        """
    )
else:
    print("Usage: dedupe-signals.sh [db_path] [30min|callsign]", file=sys.stderr)
    sys.exit(1)

con.commit()
after = con.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
print(f"removed {before - after} rows ({before} -> {after}) mode={mode}")
PY
