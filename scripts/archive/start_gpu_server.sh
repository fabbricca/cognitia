#!/bin/bash
#
# GLaDOS GPU Server Startup Script
# Run this on your GPU server to start all services
#
# Usage: ./start_gpu_server.sh [--no-rvc] [--fast]
#
# Options:
#   --no-rvc    Disable RVC voice cloning (faster response)
#   --fast      Use GLaDOS voice without RVC (fastest)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLADOS_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$GLADOS_DIR/configs/glados_network_config.yaml"
LOG_DIR="/tmp/glados_logs"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
USE_RVC=true
VOICE="af_bella"

for arg in "$@"; do
    case $arg in
        --no-rvc)
            USE_RVC=false
            ;;
        --fast)
            USE_RVC=false
            VOICE="glados"
            ;;
        *)
            ;;
    esac
done

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}     GLaDOS GPU Server Startup        ${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""

# Create log directory
mkdir -p "$LOG_DIR"

# Function to check if a service is running
check_service() {
    local name=$1
    local url=$2
    local max_attempts=${3:-30}
    
    echo -n "Waiting for $name..."
    for i in $(seq 1 $max_attempts); do
        if curl -s "$url" > /dev/null 2>&1; then
            echo -e " ${GREEN}OK${NC}"
            return 0
        fi
        sleep 1
        echo -n "."
    done
    echo -e " ${RED}FAILED${NC}"
    return 1
}

# Check for Python dependencies
echo -e "${YELLOW}[0/4] Checking dependencies...${NC}"
if ! python -c "import loguru" 2>/dev/null; then
    echo -e "${RED}Error: Python dependencies not found.${NC}"
    echo "Please run: pip install -r requirements.txt"
    exit 1
fi

# Step 1: Check/Start Ollama
echo -e "${YELLOW}[1/4] Checking Ollama...${NC}"
if ! pgrep -x "ollama" > /dev/null; then
    echo "Starting Ollama..."
    nohup ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
    sleep 3
fi
check_service "Ollama" "http://localhost:11434/api/tags" || {
    echo -e "${RED}Error: Ollama failed to start${NC}"
    exit 1
}

# Step 2: Start RVC Docker (if enabled)
if [ "$USE_RVC" = true ]; then
    echo -e "${YELLOW}[2/4] Starting RVC Docker...${NC}"
    cd "$GLADOS_DIR/rvc"
    docker compose up -d
    check_service "RVC" "http://localhost:5050/models" 60 || {
        echo -e "${RED}Error: RVC failed to start${NC}"
        echo "Check logs: docker logs rvc-rvc-1"
        exit 1
    }
    cd "$GLADOS_DIR"
else
    echo -e "${YELLOW}[2/4] Skipping RVC (disabled)${NC}"
fi

# Step 3: Update config if needed
echo -e "${YELLOW}[3/4] Configuring GLaDOS...${NC}"
echo "  Voice: $VOICE"
echo "  RVC: $USE_RVC"

# Step 4: Start GLaDOS
echo -e "${YELLOW}[4/4] Starting GLaDOS...${NC}"
cd "$GLADOS_DIR"

# Kill any existing GLaDOS process
pkill -f "glados.cli" 2>/dev/null || true
sleep 2

# Start GLaDOS
export PYTHONPATH="$GLADOS_DIR/src:$PYTHONPATH"
nohup python -m glados.cli start --config "$CONFIG_FILE" > "$LOG_DIR/glados.log" 2>&1 &
GLADOS_PID=$!

sleep 5

# Check if GLaDOS started
if ps -p $GLADOS_PID > /dev/null 2>&1; then
    echo -e "${GREEN}GLaDOS started successfully (PID: $GLADOS_PID)${NC}"
else
    echo -e "${RED}GLaDOS failed to start. Check logs:${NC}"
    echo "  tail -f $LOG_DIR/glados.log"
    exit 1
fi

# Get server IP
SERVER_IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}     GLaDOS Server Ready!             ${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo "Server listening on: ${SERVER_IP}:5555"
echo ""
echo "Connect from clients with:"
echo "  python glados_terminal_client.py --server ${SERVER_IP}:5555"
echo ""
echo "Logs:"
echo "  GLaDOS: tail -f $LOG_DIR/glados.log"
echo "  Ollama: tail -f $LOG_DIR/ollama.log"
if [ "$USE_RVC" = true ]; then
    echo "  RVC:    docker logs -f rvc-rvc-1"
fi
echo ""
echo "To stop: pkill -f 'glados.cli'"
