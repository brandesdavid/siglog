#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SIGLOG_INSTALL_LOCAL="$SCRIPT_DIR"
exec bash "$SCRIPT_DIR/install.sh" "$@"
