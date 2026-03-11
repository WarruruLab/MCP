#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/mcp}"
SERVICE_NAME="${2:-mcp}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[1/7] apt packages install"
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl

echo "[2/7] project dir check: ${PROJECT_DIR}"
if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Project directory not found: ${PROJECT_DIR}" >&2
  exit 1
fi

cd "${PROJECT_DIR}"

echo "[3/7] virtualenv setup"
${PYTHON_BIN} -m venv .venv
source .venv/bin/activate

echo "[4/7] python dependencies install"
pip install --upgrade pip
pip install -r requirements.txt

echo "[5/7] env file setup"
if [[ ! -f ".env" && -f ".env.example" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit values before production use."
fi

echo "[6/7] systemd service install"
sudo cp deploy/mcp.service "/etc/systemd/system/${SERVICE_NAME}.service"
sudo sed -i "s|/opt/mcp|${PROJECT_DIR}|g" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo sed -i "s|User=ubuntu|User=$(whoami)|g" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo sed -i "s|Group=ubuntu|Group=$(id -gn)|g" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

echo "[7/7] service start"
sudo systemctl restart "${SERVICE_NAME}"
sudo systemctl status "${SERVICE_NAME}" --no-pager

echo
echo "Done."
echo "Check logs with: journalctl -u ${SERVICE_NAME} -f"
