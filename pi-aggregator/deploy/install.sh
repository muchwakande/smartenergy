#!/usr/bin/env bash
# Installs/updates the Pi aggregator as a systemd service. Run this ON the
# Pi, from a checkout of this repo (re-run after `git pull` to redeploy).
set -euo pipefail

cd "$(dirname "$0")/../.."
APP_DIR="$(pwd)"
RUN_USER="$(whoami)"
SERVICE_NAME="smartenergy-aggregator"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "Missing $APP_DIR/.env - copy .env.example to .env and fill in real values first." >&2
  exit 1
fi

python3 -m venv "$APP_DIR/pi-aggregator/.venv"
"$APP_DIR/pi-aggregator/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/pi-aggregator/.venv/bin/pip" install -q -r "$APP_DIR/pi-aggregator/requirements.txt"

mkdir -p "$APP_DIR/pi-aggregator/data/archive"

# Only needed for the optional PZEM-004T wired directly into the Pi -
# harmless if you're not using that feature. Takes effect on next login.
sudo usermod -aG dialout "$RUN_USER"

sed "s|__APP_DIR__|$APP_DIR|g; s|__RUN_USER__|$RUN_USER|g" \
  "$APP_DIR/pi-aggregator/deploy/smartenergy-aggregator.service" \
  | sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

# mDNS/DNS-SD advertisement (_smartenergy._tcp) so NodeMCUs can discover the
# aggregator without a hardcoded IP. avahi-daemon ships enabled by default on
# Raspberry Pi OS (it's what makes raspberrypi.local resolve); install it
# only if it's somehow missing.
if ! dpkg -s avahi-daemon >/dev/null 2>&1; then
  sudo apt-get install -y avahi-daemon
fi

LISTEN_PORT="$(grep '^LISTEN_PORT=' "$APP_DIR/.env" | cut -d= -f2- || true)"
LISTEN_PORT="${LISTEN_PORT:-8080}"

sed "s|__LISTEN_PORT__|$LISTEN_PORT|g" \
  "$APP_DIR/pi-aggregator/deploy/smartenergy-aggregator.avahi-service" \
  | sudo tee /etc/avahi/services/smartenergy-aggregator.service > /dev/null

sudo systemctl restart avahi-daemon

echo "Deployed. Status: sudo systemctl status $SERVICE_NAME"
echo "Logs:             sudo journalctl -u $SERVICE_NAME -f"
echo "If you weren't already in the dialout group, log out/in (or reboot) before using the local PZEM sensor."
