#!/usr/bin/env bash
set -euo pipefail

# Raspberry Pi / Debian setup helper for Docker + Compose
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Install Docker engine
sudo apt-get install -y docker.io
sudo systemctl enable --now docker

# Try Compose v2 plugin first; fall back to downloading the standalone binary when
# the plugin package is unavailable (common on Raspberry Pi OS).
if sudo apt-get install -y docker-compose-plugin; then
  echo "[install_pi] docker-compose-plugin installed"
else
  echo "[install_pi] docker-compose-plugin not found; installing standalone docker-compose binary"

  COMPOSE_VERSION="v2.29.2"
  ARCH=$(uname -m)
  case "$ARCH" in
    x86_64|amd64)
      COMPOSE_ARCH="x86_64" ;;
    armv7l|armv7)
      COMPOSE_ARCH="armv7" ;;
    aarch64|arm64)
      COMPOSE_ARCH="arm64" ;;
    *)
      echo "[install_pi] Unsupported architecture $ARCH; please install docker-compose manually" >&2
      exit 1 ;;
  esac

  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${COMPOSE_ARCH}" \
    | sudo tee /usr/local/lib/docker/cli-plugins/docker-compose >/dev/null
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  echo "[install_pi] Installed docker-compose ${COMPOSE_VERSION} for ${COMPOSE_ARCH}"
fi

echo "[install_pi] Docker setup complete. You may need to log out/in for group membership."
