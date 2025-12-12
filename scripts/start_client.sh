#!/bin/bash
# GLaDOS Client Launcher
# Supports --web, --tui, or --cli modes

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

# Default server
DEFAULT_SERVER="iberu.me:12345"
SERVER="$DEFAULT_SERVER"
MODE=""
AUTH_TOKEN="${AUTH_TOKEN:-}"

cd "$PROJECT_ROOT"

# Helper functions
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_step() {
    echo -e "${GREEN}▶ $1${NC}"
}

# Show usage
show_usage() {
    cat << EOF
Usage: $0 [MODE] [OPTIONS]

Launch GLaDOS client in different modes.

Modes:
  --web           Open web interface in browser (default server: $DEFAULT_SERVER)
  --tui           Launch Textual TUI client
  --cli           Launch legacy CLI client

Options:
  --server HOST:PORT    Server address (default: $DEFAULT_SERVER)
  --auth-token TOKEN    JWT authentication token
  --help                Show this help message

Environment Variables:
  AUTH_TOKEN            JWT authentication token

Examples:
  # Web interface (default server)
  $0 --web

  # Web interface (custom server)
  $0 --web --server localhost:8080

  # TUI client
  $0 --tui
  $0 --tui --server 192.168.1.100:5555

  # CLI client
  $0 --cli
  $0 --cli --server localhost:5555 --auth-token "eyJhbG..."

Default:
  If no mode is specified, defaults to --web with server $DEFAULT_SERVER

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --web)
            MODE="web"
            shift
            ;;
        --tui)
            MODE="tui"
            shift
            ;;
        --cli)
            MODE="cli"
            shift
            ;;
        --server)
            SERVER="$2"
            shift 2
            ;;
        --auth-token)
            AUTH_TOKEN="$2"
            shift 2
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

# Default to web mode if no mode specified
if [ -z "$MODE" ]; then
    MODE="web"
fi

# Parse server into host and port
if [[ "$SERVER" == *":"* ]]; then
    SERVER_HOST="${SERVER%:*}"
    SERVER_PORT="${SERVER#*:}"
else
    SERVER_HOST="$SERVER"
    SERVER_PORT="5555"
fi

# Launch based on mode
case $MODE in
    web)
        print_step "Opening web interface..."

        # Determine URL
        if [ "$SERVER_HOST" == "localhost" ] || [ "$SERVER_HOST" == "127.0.0.1" ]; then
            # Local server - use HTTP with web port
            WEB_PORT="${WEB_PORT:-8080}"
            URL="http://localhost:$WEB_PORT"
        else
            # Remote server - use HTTPS (assuming production setup)
            # Extract base domain (remove port if present)
            BASE_DOMAIN="${SERVER_HOST%%:*}"
            URL="https://$BASE_DOMAIN"
        fi

        print_success "Opening: $URL"

        # Try to open browser
        if command -v xdg-open &> /dev/null; then
            xdg-open "$URL"
        elif command -v open &> /dev/null; then
            open "$URL"
        elif command -v start &> /dev/null; then
            start "$URL"
        else
            echo ""
            echo "Please open this URL in your browser:"
            echo "  $URL"
            echo ""
        fi
        ;;

    tui)
        print_step "Launching TUI client..."

        # Check if venv exists
        if [ -d "$VENV_DIR" ]; then
            source "$VENV_DIR/bin/activate"
        else
            print_error "Virtual environment not found!"
            echo "Please run scripts/start_server.sh first to set up environment"
            exit 1
        fi

        # Check if textual client exists
        if [ ! -f "network/glados_textual_client.py" ]; then
            print_error "TUI client not found: network/glados_textual_client.py"
            exit 1
        fi

        # Build command
        CMD="python3 network/glados_textual_client.py --server $SERVER_HOST:$SERVER_PORT"

        if [ -n "$AUTH_TOKEN" ]; then
            print_step "Using authentication token"
            CMD="$CMD --auth-token \"$AUTH_TOKEN\""
        fi

        print_success "Connecting to: $SERVER_HOST:$SERVER_PORT"
        echo ""

        # Execute TUI client
        exec bash -c "$CMD"
        ;;

    cli)
        print_step "Launching CLI client..."

        # Check if venv exists
        if [ -d "$VENV_DIR" ]; then
            source "$VENV_DIR/bin/activate"
        else
            print_error "Virtual environment not found!"
            echo "Please run scripts/start_server.sh first to set up environment"
            exit 1
        fi

        # Check if terminal client exists
        if [ ! -f "network/glados_terminal_client.py" ]; then
            print_error "CLI client not found: network/glados_terminal_client.py"
            exit 1
        fi

        # Build command
        CMD="python3 network/glados_terminal_client.py --server $SERVER_HOST:$SERVER_PORT"

        if [ -n "$AUTH_TOKEN" ]; then
            print_step "Using authentication token"
            CMD="$CMD --auth-token \"$AUTH_TOKEN\""
        fi

        print_success "Connecting to: $SERVER_HOST:$SERVER_PORT"
        echo ""

        # Execute CLI client
        exec bash -c "$CMD"
        ;;

    *)
        print_error "Invalid mode: $MODE"
        show_usage
        exit 1
        ;;
esac
