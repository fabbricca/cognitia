#!/bin/bash
# GLaDOS Client Start Script
# Terminal client with voice and text input support
# v2.1+: JWT authentication support

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
SERVER_HOST="${SERVER_HOST:-localhost}"
SERVER_PORT="${SERVER_PORT:-5555}"
MIC_MUTED="${MIC_MUTED:-false}"
USE_LEGACY="${USE_LEGACY:-false}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
AUTH_TOKEN_FILE="${AUTH_TOKEN_FILE:-}"

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

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check Python
check_python() {
    if ! command_exists python3; then
        print_error "Python 3 not found!"
        exit 1
    fi
}

# Setup virtual environment
setup_venv() {
    if [ -d "$VENV_DIR" ]; then
        source "$VENV_DIR/bin/activate"
        print_success "Virtual environment activated"
    else
        print_warning "Virtual environment not found"
        print_step "Run ./scripts/start_server.sh first to set up environment"

        read -p "Create virtual environment now? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python3 -m venv "$VENV_DIR"
            source "$VENV_DIR/bin/activate"
            pip install --upgrade pip -q
            pip install sounddevice numpy -q
            print_success "Virtual environment created and activated"
        else
            exit 1
        fi
    fi
}

# Check client dependencies
check_client_deps() {
    print_step "Checking client dependencies..."

    # Check for sounddevice
    if ! python3 -c "import sounddevice" 2>/dev/null; then
        print_warning "sounddevice not installed"
        print_step "Installing sounddevice..."
        pip install sounddevice numpy -q
    fi

    # Check for numpy
    if ! python3 -c "import numpy" 2>/dev/null; then
        print_warning "numpy not installed"
        print_step "Installing numpy..."
        pip install numpy -q
    fi

    # Check for textual (for TUI mode)
    if [ "$USE_LEGACY" != "true" ]; then
        if ! python3 -c "import textual" 2>/dev/null; then
            print_warning "textual not installed (required for modern TUI)"
            print_step "Installing textual..."
            pip install textual rich -q

            if ! python3 -c "import textual" 2>/dev/null; then
                print_warning "Failed to install textual, falling back to legacy client"
                USE_LEGACY="true"
            fi
        fi
    fi

    print_success "Client dependencies OK"
}

# Check server connection
check_server() {
    print_step "Checking server connection..."

    # Try to connect to server
    if timeout 2 bash -c "echo >/dev/tcp/$SERVER_HOST/$SERVER_PORT" 2>/dev/null; then
        print_success "Server is reachable at $SERVER_HOST:$SERVER_PORT"
    else
        print_error "Cannot connect to server at $SERVER_HOST:$SERVER_PORT"
        echo ""
        echo "Make sure the server is running:"
        echo "  ./scripts/start_server.sh"
        echo ""
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Check audio devices
check_audio() {
    print_step "Checking audio devices..."

    # List audio devices
    python3 << 'EOF' 2>&1 | grep -v "ALSA lib" || true
import sounddevice as sd
try:
    devices = sd.query_devices()
    print("\nAvailable audio devices:")
    for i, dev in enumerate(devices):
        if isinstance(dev, dict):
            print(f"  [{i}] {dev.get('name', 'Unknown')}")
except Exception as e:
    print(f"Warning: Could not query audio devices: {e}")
EOF

    print_success "Audio check complete"
}

# Start client
start_client() {
    print_header "Starting GLaDOS Client"

    # Choose client based on mode
    if [ "$USE_LEGACY" == "true" ]; then
        CLIENT_SCRIPT="network/glados_terminal_client.py"
        CLIENT_NAME="GLaDOS Legacy Terminal Client"
    else
        CLIENT_SCRIPT="network/glados_textual_client.py"
        CLIENT_NAME="GLaDOS Modern TUI Client"
    fi

    # Check if client script exists
    if [ ! -f "$CLIENT_SCRIPT" ]; then
        print_error "Client script not found: $CLIENT_SCRIPT"
        exit 1
    fi

    print_step "Connecting to: $SERVER_HOST:$SERVER_PORT"

    # Build command
    CMD="python3 $CLIENT_SCRIPT --server $SERVER_HOST:$SERVER_PORT"

    # Add authentication if provided (v2.1+)
    if [ -n "$AUTH_TOKEN" ]; then
        print_step "Using JWT authentication token"
        CMD="$CMD --auth-token \"$AUTH_TOKEN\""
    elif [ -n "$AUTH_TOKEN_FILE" ]; then
        if [ -f "$AUTH_TOKEN_FILE" ]; then
            print_step "Using JWT token from file: $AUTH_TOKEN_FILE"
            CMD="$CMD --auth-token-file \"$AUTH_TOKEN_FILE\""
        else
            print_error "Token file not found: $AUTH_TOKEN_FILE"
            exit 1
        fi
    fi

    # Legacy client supports --muted flag
    if [ "$MIC_MUTED" == "true" ] && [ "$USE_LEGACY" == "true" ]; then
        print_warning "Microphone will be muted (text-only mode)"
        CMD="$CMD --muted"
    fi

    if [ "$USE_LEGACY" != "true" ]; then
        print_success "Starting modern TUI (Textual-based)..."
        print_step "Press Ctrl+C to exit"
    else
        print_success "Starting legacy client..."
        echo ""
        echo -e "${BLUE}============================================================${NC}"
        echo -e "${BLUE}  $CLIENT_NAME${NC}"
        echo -e "${BLUE}============================================================${NC}"
        echo ""
        echo "Controls:"
        echo "  - Type and press Enter to send text"
        echo "  - Speak if microphone is enabled"
        echo "  - Press Ctrl+C to exit"
        echo ""
        echo "Connecting..."
        echo ""
    fi

    # Execute client
    exec $CMD
}

# Show usage
show_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Start the GLaDOS client (modern TUI by default).

Options:
  --server HOST:PORT      Server address (default: $SERVER_HOST:$SERVER_PORT)
  --auth-token TOKEN      JWT authentication token (v2.1+)
  --auth-token-file PATH  Path to file containing JWT token (v2.1+)
  --muted                 Start with microphone muted (text-only, legacy only)
  --legacy                Use legacy terminal client instead of TUI
  --help                  Show this help message

Environment Variables:
  SERVER_HOST         Server hostname (default: localhost)
  SERVER_PORT         Server port (default: 5555)
  AUTH_TOKEN          JWT authentication token
  AUTH_TOKEN_FILE     Path to JWT token file (e.g., ~/.glados_token)
  MIC_MUTED           Set to 'true' for text-only mode (legacy only)
  USE_LEGACY          Set to 'true' to use legacy client

Examples:
  # Basic usage
  $0                                    # Modern TUI client (no auth)
  $0 --server 192.168.1.100:5555        # Connect to remote server

  # With authentication (v2.1+)
  $0 --auth-token "eyJhbG..."           # Authenticate with JWT token
  $0 --auth-token-file ~/.glados_token  # Token from file
  AUTH_TOKEN_FILE=~/.glados_token $0    # Using environment variable

  # Legacy client
  $0 --legacy                           # Use legacy client
  $0 --legacy --muted                   # Legacy client, text-only

TUI Features:
  - Beautiful split-pane interface
  - Real-time status indicators
  - Keyboard shortcuts (Ctrl+W: delete word, Ctrl+L: clear)
  - Message history (Up/Down arrows)
  - Authentication support (v2.1+)
  - No message duplication

Authentication (v2.1+):
  If the server requires authentication, use --auth-token or --auth-token-file.
  Get your token from an admin or use scripts/create_admin.py to create an account.

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --server)
            if [[ "$2" == *":"* ]]; then
                SERVER_HOST="${2%:*}"
                SERVER_PORT="${2#*:}"
            else
                SERVER_HOST="$2"
            fi
            shift 2
            ;;
        --auth-token)
            AUTH_TOKEN="$2"
            shift 2
            ;;
        --auth-token-file)
            AUTH_TOKEN_FILE="$2"
            shift 2
            ;;
        --muted)
            MIC_MUTED="true"
            shift
            ;;
        --legacy)
            USE_LEGACY="true"
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main execution
main() {
    check_python
    setup_venv
    check_client_deps
    check_server
    check_audio
    start_client
}

# Trap Ctrl+C
trap 'echo ""; echo "Client stopped."; exit 0' INT

# Run main function
main
