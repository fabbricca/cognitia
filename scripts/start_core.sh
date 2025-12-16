#!/bin/bash
# Cognitia Core GPU Server Startup Script
# Run this on your GPU machine to start the AI processing server

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON_VERSION="3.12"

# Server configuration
HOST="${COGNITIA_HOST:-0.0.0.0}"
PORT="${COGNITIA_PORT:-8001}"
RELOAD="${COGNITIA_RELOAD:-false}"
WORKERS="${COGNITIA_WORKERS:-1}"

# Helper functions
print_header() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
}

print_step() {
    echo -e "${CYAN}▶${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --reload)
            RELOAD="true"
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --reload      Enable auto-reload for development"
            echo "  --port PORT   Server port (default: 8001)"
            echo "  --host HOST   Server host (default: 0.0.0.0)"
            echo "  --workers N   Number of workers (default: 1)"
            echo "  -h, --help    Show this help"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

cd "$PROJECT_ROOT"

print_header "Cognitia Core GPU Server"

# ─────────────────────────────────────────────────────────────────────────────
# System Checks
# ─────────────────────────────────────────────────────────────────────────────

print_step "Checking system requirements..."

# Check Python
if command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    ACTUAL_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if [[ "$ACTUAL_VERSION" < "3.10" ]]; then
        print_error "Python 3.10+ required, found $ACTUAL_VERSION"
        print_step "Install with: sudo pacman -S python"
        exit 1
    fi
else
    print_error "Python 3 not found!"
    print_step "Install with: sudo pacman -S python"
    exit 1
fi
print_success "Python: $($PYTHON_CMD --version)"

# Check CUDA/GPU
if command -v nvidia-smi &> /dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    if [ -n "$GPU_INFO" ]; then
        print_success "GPU: $GPU_INFO"
    fi
else
    print_warning "nvidia-smi not found - GPU acceleration may not work"
fi

# Check Ollama
if command -v ollama &> /dev/null; then
    if systemctl is-active --quiet ollama 2>/dev/null || pgrep -x ollama > /dev/null; then
        print_success "Ollama: running"
    else
        print_warning "Ollama installed but not running"
        print_step "Start with: systemctl start ollama"
    fi
else
    print_warning "Ollama not found - LLM features will not work"
    print_step "Install from: https://ollama.ai"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Virtual Environment Setup
# ─────────────────────────────────────────────────────────────────────────────

if [ ! -d "$VENV_DIR" ]; then
    print_step "Creating virtual environment..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    print_success "Virtual environment created at $VENV_DIR"
fi

print_step "Activating virtual environment..."
source "$VENV_DIR/bin/activate"
print_success "Virtual environment activated"

# ─────────────────────────────────────────────────────────────────────────────
# Dependencies Installation
# ─────────────────────────────────────────────────────────────────────────────

print_step "Checking dependencies..."

# Check if package is installed in editable mode
if ! pip show cognitia &> /dev/null; then
    print_step "Installing cognitia package..."
    pip install --upgrade pip wheel setuptools -q
    
    # Install with CUDA support
    pip install -e ".[cuda]" -q
    print_success "Cognitia package installed with CUDA support"
else
    print_success "Cognitia package already installed"
fi

# Ensure FastAPI and uvicorn are installed
if ! pip show fastapi &> /dev/null || ! pip show uvicorn &> /dev/null; then
    print_step "Installing server dependencies..."
    pip install fastapi "uvicorn[standard]" -q
fi

# ─────────────────────────────────────────────────────────────────────────────
# Start Server
# ─────────────────────────────────────────────────────────────────────────────

echo ""
print_header "Starting Core Server"
echo -e "  Host: ${CYAN}$HOST${NC}"
echo -e "  Port: ${CYAN}$PORT${NC}"
echo -e "  Reload: ${CYAN}$RELOAD${NC}"
echo -e "  Workers: ${CYAN}$WORKERS${NC}"
echo ""

# Build uvicorn command
UVICORN_CMD="uvicorn cognitia.core.server:app --host $HOST --port $PORT"

if [ "$RELOAD" = "true" ]; then
    UVICORN_CMD="$UVICORN_CMD --reload"
else
    UVICORN_CMD="$UVICORN_CMD --workers $WORKERS"
fi

print_step "Running: $UVICORN_CMD"
echo ""

exec $UVICORN_CMD
