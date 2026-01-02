#!/usr/bin/env bash
set -euo pipefail

# Raspberry Pi / Debian setup helper for Docker + Compose
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Install Docker engine
sudo apt-get install -y docker.io
sudo systemctl enable --now docker

# Try Compose v2 plugin first; fall back to classic docker-compose if unavailable
if sudo apt-get install -y docker-compose-plugin; then
  echo "[install_pi] docker-compose-plugin installed"
else
  echo "[install_pi] docker-compose-plugin not found; installing docker-compose instead"
  sudo apt-get install -y docker-compose
fi

echo "[install_pi] Docker setup complete. You may need to log out/in for group membership."
