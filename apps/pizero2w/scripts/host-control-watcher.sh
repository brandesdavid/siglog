#!/bin/sh
set -eu
CONTROL_DIR="${SIGLOG_CONTROL_DIR:-$HOME/siglog/control}"
mkdir -p "$CONTROL_DIR"
while true; do
  if [ -f "$CONTROL_DIR/host.cmd" ]; then
    cmd=$(tr -d '\n\r' < "$CONTROL_DIR/host.cmd")
    rm -f "$CONTROL_DIR/host.cmd"
    if command -v siglog-net >/dev/null 2>&1; then
      siglog-net "$cmd" > "$CONTROL_DIR/host.result" 2>&1 || true
    else
      echo "siglog-net not found" > "$CONTROL_DIR/host.result"
    fi
  fi
  sleep 2
done
