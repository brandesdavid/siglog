#!/bin/bash
set -euo pipefail

if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ -f "${BASH_SOURCE[0]}" ]]; then
  _INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$_INSTALL_DIR/scripts/pi-bootstrap.sh" ]]; then
    export SIGLOG_INSTALL_LOCAL="$_INSTALL_DIR"
  fi
fi

SIGLOG_PI_DIR="${SIGLOG_PI_DIR:-$HOME/siglog}"
mkdir -p "$SIGLOG_PI_DIR/scripts"

_bootstrap="${SIGLOG_INSTALL_LOCAL:-}/scripts/pi-bootstrap.sh"
if [[ ! -f "$_bootstrap" ]]; then
  repo="${GITHUB_REPO:-brandesdavid/siglog}"
  branch="${GITHUB_BRANCH:-main}"
  curl -fsSL -o "$SIGLOG_PI_DIR/scripts/pi-bootstrap.sh" \
    "https://raw.githubusercontent.com/${repo}/${branch}/apps/pizero2w/scripts/pi-bootstrap.sh"
  _bootstrap="$SIGLOG_PI_DIR/scripts/pi-bootstrap.sh"
fi

# shellcheck disable=SC1090
source "$_bootstrap"

case "${1:-install}" in
  install|"") siglog_full_install ;;
  sync) siglog_sync_scripts; echo "Scripts synced to $SIGLOG_PI_DIR" ;;
  docker|update) siglog_docker_update; echo "Container updated." ;;
  wifi) siglog_install_wifi; siglog_apply_hotspot_secrets; echo "WiFi auto configured." ;;
  *)
    echo "Usage: install.sh [install|sync|docker|wifi]"
    exit 1
    ;;
esac
