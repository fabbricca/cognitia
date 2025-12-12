#!/bin/bash
# GLaDOS Server - All-in-One Startup Script
# Starts GLaDOS main server + WebSocket bridge + Web frontend

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
BRIDGE_VENV_DIR="$PROJECT_ROOT/websocket-bridge/venv"

# Server configuration
GLADOS_CONFIG="${GLADOS_CONFIG:-configs/glados_network_config.yaml}"
GLADOS_HOST="${GLADOS_HOST:-0.0.0.0}"
GLADOS_PORT="${GLADOS_PORT:-5555}"
WEBSOCKET_PORT="${WEBSOCKET_PORT:-8765}"
WEB_PORT="${WEB_PORT:-8080}"

cd "$PROJECT_ROOT"

# Helper functions
print_header() {
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

print_step() {
    echo -e "${GREEN}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Cleanup function
cleanup() {
    echo ""
    print_step "Stopping all services..."

    if [ -n "$GLADOS_PID" ] && kill -0 $GLADOS_PID 2>/dev/null; then
        kill $GLADOS_PID 2>/dev/null || true
        print_success "GLaDOS server stopped"
    fi

    if [ -n "$BRIDGE_PID" ] && kill -0 $BRIDGE_PID 2>/dev/null; then
        kill $BRIDGE_PID 2>/dev/null || true
        print_success "WebSocket bridge stopped"
    fi

    if [ -n "$WEB_PID" ] && kill -0 $WEB_PID 2>/dev/null; then
        kill $WEB_PID 2>/dev/null || true
        print_success "Web frontend stopped"
    fi

    # Clean up PID files
    rm -f /tmp/glados_server.pid /tmp/glados_bridge.pid /tmp/glados_web.pid

    echo ""
    print_success "All services stopped"
    exit 0
}

trap cleanup INT TERM

# Check if Python exists
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 not found!"
    exit 1
fi

print_header "GLaDOS All-in-One Server"
echo "Project: $PROJECT_ROOT"
echo "Config: $GLADOS_CONFIG"
echo ""

# 1. Start GLaDOS Main Server
print_step "Starting GLaDOS main server..."

if [ ! -f "$GLADOS_CONFIG" ]; then
    print_error "Config file not found: $GLADOS_CONFIG"
    exit 1
fi

# Activate main venv if exists
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
fi

# Start GLaDOS server
nohup python3 -m glados.cli start --config "$GLADOS_CONFIG" > /tmp/glados_server.log 2>&1 &
GLADOS_PID=$!
echo $GLADOS_PID > /tmp/glados_server.pid

sleep 2

if kill -0 $GLADOS_PID 2>/dev/null; then
    print_success "GLaDOS server running (PID: $GLADOS_PID) on $GLADOS_HOST:$GLADOS_PORT"
else
    print_error "GLaDOS server failed to start!"
    tail -20 /tmp/glados_server.log
    exit 1
fi

# 2. Start WebSocket Bridge
print_step "Starting WebSocket bridge..."

cd "$PROJECT_ROOT/websocket-bridge"

# Create bridge venv if doesn't exist
if [ ! -d "venv" ]; then
    print_step "Creating virtual environment for bridge..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
else
    source venv/bin/activate
fi

# Start bridge
nohup python3 bridge_server.py > /tmp/glados_bridge.log 2>&1 &
BRIDGE_PID=$!
echo $BRIDGE_PID > /tmp/glados_bridge.pid

sleep 2

if kill -0 $BRIDGE_PID 2>/dev/null; then
    print_success "WebSocket bridge running (PID: $BRIDGE_PID) on ws://0.0.0.0:$WEBSOCKET_PORT"
else
    print_error "WebSocket bridge failed to start!"
    tail -20 /tmp/glados_bridge.log
    cleanup
    exit 1
fi

cd "$PROJECT_ROOT"

# 3. Start Web Frontend
print_step "Starting web frontend..."

cd "$PROJECT_ROOT/web"

nohup python3 -m http.server $WEB_PORT > /tmp/glados_web.log 2>&1 &
WEB_PID=$!
echo $WEB_PID > /tmp/glados_web.pid

sleep 1

if kill -0 $WEB_PID 2>/dev/null; then
    print_success "Web frontend running (PID: $WEB_PID) on http://0.0.0.0:$WEB_PORT"
else
    print_error "Web frontend failed to start!"
    cleanup
    exit 1
fi

cd "$PROJECT_ROOT"

# All services started successfully
print_header "All Services Running!"
echo ""
echo "GLaDOS Server:"
echo "  PID: $GLADOS_PID"
echo "  Port: $GLADOS_PORT"
echo "  Log: /tmp/glados_server.log"
echo ""
echo "WebSocket Bridge:"
echo "  PID: $BRIDGE_PID"
echo "  Port: $WEBSOCKET_PORT (ws://0.0.0.0:$WEBSOCKET_PORT)"
echo "  Log: /tmp/glados_bridge.log"
echo ""
echo "Web Frontend:"
echo "  PID: $WEB_PID"
echo "  Port: $WEB_PORT (http://0.0.0.0:$WEB_PORT)"
echo "  Log: /tmp/glados_web.log"
echo ""
echo "Access the web interface:"
echo "  Local:  http://localhost:$WEB_PORT"
echo "  Remote: http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
echo ""
echo "Commands:"
echo "  Monitor GLaDOS: tail -f /tmp/glados_server.log"
echo "  Monitor Bridge: tail -f /tmp/glados_bridge.log"
echo "  Monitor Web:    tail -f /tmp/glados_web.log"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Wait for any process to exit
wait
