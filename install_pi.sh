#!/usr/bin/env bash
# Automated installer for Raspberry Pi OS / Debian (64-bit)
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Please run this script with sudo or as root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
DEFAULT_USER="${SUDO_USER:-$(whoami)}"

log() { echo "[install] $*"; }

ensure_package() {
  local pkg="$1"
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    log "Installing $pkg"
    apt-get install -y "$pkg"
  fi
}

ensure_compose() {
  # Prefer the Docker Compose plugin if present in apt, otherwise fall back to docker-compose
  if apt-cache show docker-compose-plugin >/dev/null 2>&1; then
    ensure_package docker-compose-plugin
  elif apt-cache show docker-compose >/dev/null 2>&1; then
    ensure_package docker-compose
  else
    log "ERROR: Neither docker-compose-plugin nor docker-compose is available from your apt sources."
    log "       Enable Docker's official apt repo, or use a distro repo that provides one of them."
    exit 1
  fi
}

compose() {
  # Works whether we have the plugin ("docker compose") or standalone ("docker-compose")
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    log "ERROR: Docker Compose is not available."
    exit 1
  fi
}

log "Updating apt cache"
apt-get update -y

# Core dependencies
ensure_package ca-certificates
ensure_package curl
ensure_package git
ensure_package jq
ensure_package openssl

# Docker (Debian/RPi OS repo)
ensure_package docker.io
ensure_compose

# Python tooling (prevents 'pip not found under sudo' / enables venv if needed later)
ensure_package python3
ensure_package python3-pip
ensure_package python3-venv

log "Enabling and starting Docker service"
systemctl enable --now docker

if ! id -nG "$DEFAULT_USER" | grep -qw docker; then
  log "Adding $DEFAULT_USER to docker group"
  usermod -aG docker "$DEFAULT_USER"
fi

# Prepare project env file with sensible defaults
if [ ! -f "$ENV_FILE" ]; then
  log "Creating .env with defaults"
  POSTGRES_USER_VALUE=${POSTGRES_USER:-spool}
  POSTGRES_DB_VALUE=${POSTGRES_DB:-spooldb}
  POSTGRES_PASSWORD_VALUE=${POSTGRES_PASSWORD:-$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24)}
  BACKUP_INTERVAL_VALUE=${BACKUP_INTERVAL:-86400}

  cat > "$ENV_FILE" <<EOF_ENV
POSTGRES_USER=${POSTGRES_USER_VALUE}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD_VALUE}
POSTGRES_DB=${POSTGRES_DB_VALUE}
DOCKER_PLATFORM=linux/arm64/v8
BACKUP_INTERVAL=${BACKUP_INTERVAL_VALUE}
EOF_ENV
else
  log "Existing .env detected; leaving in place"
fi

log "Project directory: $SCRIPT_DIR"
cd "$SCRIPT_DIR"

log "Pulling container images (may take a while)"
compose pull || true

log "Building and starting the stack"
compose up -d --build

log "Setup complete."
log "If this was run with sudo, log out/in to refresh docker group membership for $DEFAULT_USER."
