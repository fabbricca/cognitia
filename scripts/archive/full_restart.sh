#!/bin/bash
#
# Full System Restart
# Restarts RVC (Docker) and GLaDOS to ensure new models are loaded
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLADOS_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/tmp/glados_logs"

echo "=== Full System Restart ==="

# 1. Stop GLaDOS
echo "Stopping GLaDOS..."
pkill -f "glados.cli" || true
pkill -f "ollama" || true

# 2. Restart RVC Docker (to load new models)
echo "Restarting RVC Docker..."
cd "$GLADOS_DIR/rvc"
docker compose restart
echo "Waiting for RVC to initialize (10s)..."
sleep 10

# 3. Start everything back up
echo "Starting GPU Server..."
"$SCRIPT_DIR/start_gpu_server.sh"
