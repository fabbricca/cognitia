#!/bin/bash
# GLaDOS Server Start Script v2.1
# Comprehensive server startup with JWT authentication, dependency checks, and service management

set -e  # Exit on error

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
PYTHON_MIN_VERSION="3.10"
CONFIG_FILE="${CONFIG_FILE:-configs/glados_network_config.yaml}"
SKIP_TESTS="${SKIP_TESTS:-false}"
SKIP_RVC="${SKIP_RVC:-false}"
ENABLE_AUTH="${ENABLE_AUTH:-true}"  # v2.1: Default to auth enabled

# Authentication configuration
DB_PATH="$PROJECT_ROOT/data/users.db"
JWT_SECRET_FILE="$PROJECT_ROOT/data/.jwt_secret"
AUTH_SERVER_SCRIPT="$PROJECT_ROOT/server_with_auth.py"

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

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Version comparison
version_ge() {
    printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

# Check Python version
check_python() {
    print_step "Checking Python installation..."

    if ! command_exists python3; then
        print_error "Python 3 not found!"
        echo "Please install Python ${PYTHON_MIN_VERSION} or higher"
        echo "  Arch Linux: sudo pacman -S python"
        echo "  Ubuntu/Debian: sudo apt install python3"
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Found Python ${PYTHON_VERSION}"

    if ! version_ge "$PYTHON_VERSION" "$PYTHON_MIN_VERSION"; then
        print_error "Python ${PYTHON_MIN_VERSION}+ required, found ${PYTHON_VERSION}"
        exit 1
    fi
}

# Check system dependencies
check_system_deps() {
    print_step "Checking system dependencies..."

    local missing_deps=()

    # Check for git
    if ! command_exists git; then
        missing_deps+=("git")
    fi

    # Check for docker (optional, for RVC)
    if ! command_exists docker && [ "$SKIP_RVC" != "true" ]; then
        print_warning "Docker not found - RVC service will be disabled"
        SKIP_RVC="true"
    fi

    # Check for docker-compose (optional, for RVC)
    if ! command_exists docker-compose && ! docker compose version >/dev/null 2>&1; then
        if [ "$SKIP_RVC" != "true" ]; then
            print_warning "Docker Compose not found - RVC service will be disabled"
            SKIP_RVC="true"
        fi
    fi

    if [ ${#missing_deps[@]} -ne 0 ]; then
        print_error "Missing system dependencies: ${missing_deps[*]}"
        echo ""
        echo "Install with:"
        echo "  Arch Linux: sudo pacman -S ${missing_deps[*]}"
        echo "  Ubuntu/Debian: sudo apt install ${missing_deps[*]}"
        exit 1
    fi

    print_success "System dependencies OK"
}

# Check Ollama service
check_ollama() {
    print_step "Checking Ollama service..."

    if ! command_exists ollama; then
        print_warning "Ollama not found in PATH"
        echo "GLaDOS requires Ollama for LLM processing"
        echo "Install from: https://ollama.ai"
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
        return
    fi

    # Check if Ollama is running
    if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        print_warning "Ollama service not running"
        echo "Starting Ollama service..."
        ollama serve >/dev/null 2>&1 &
        sleep 3

        if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
            print_error "Failed to start Ollama service"
            echo "Please start Ollama manually: ollama serve"
            exit 1
        fi
    fi

    print_success "Ollama service running"
}

# Create or activate virtual environment
setup_venv() {
    print_step "Setting up Python virtual environment..."

    if [ ! -d "$VENV_DIR" ]; then
        print_step "Creating new virtual environment..."
        python3 -m venv "$VENV_DIR"
        print_success "Virtual environment created"
    else
        print_success "Virtual environment found"
    fi

    # Activate virtual environment
    source "$VENV_DIR/bin/activate"
    print_success "Virtual environment activated"
}

# Install Python dependencies
install_dependencies() {
    print_step "Installing Python dependencies..."

    # Upgrade pip first
    pip install --upgrade pip -q

    # Install from pyproject.toml
    if [ -f "pyproject.toml" ]; then
        print_step "Installing from pyproject.toml..."
        pip install -e ".[cuda]" -q
        print_success "Core dependencies installed"

        # Install dev dependencies for testing
        print_step "Installing dev dependencies..."
        pip install pytest pytest-cov pytest-timeout -q
        print_success "Dev dependencies installed"
    elif [ -f "requirements.txt" ]; then
        print_step "Installing from requirements.txt..."
        pip install -r requirements.txt -q
        print_success "Dependencies installed from requirements.txt"
    else
        print_error "No dependency file found (pyproject.toml or requirements.txt)"
        exit 1
    fi

    # Ensure auth dependencies are installed
    print_step "Installing authentication dependencies..."
    pip install pyjwt bcrypt -q

    print_success "All dependencies installed"
}

# Generate JWT secret
generate_jwt_secret() {
    python3 << 'EOF'
import secrets
import string

# Generate a secure random secret (64 characters)
alphabet = string.ascii_letters + string.digits + string.punctuation
secret = ''.join(secrets.choice(alphabet) for _ in range(64))
print(secret)
EOF
}

# Setup authentication database
setup_auth() {
    if [ "$ENABLE_AUTH" != "true" ]; then
        print_warning "Authentication disabled (--no-auth flag)"
        return
    fi

    print_header "Authentication Setup"

    # Create data directory if it doesn't exist
    mkdir -p "$PROJECT_ROOT/data"

    # Check if JWT secret exists
    if [ ! -f "$JWT_SECRET_FILE" ]; then
        print_step "Generating JWT secret..."
        JWT_SECRET=$(generate_jwt_secret)
        echo "$JWT_SECRET" > "$JWT_SECRET_FILE"
        chmod 600 "$JWT_SECRET_FILE"
        print_success "JWT secret generated"
    else
        print_success "JWT secret found"
        JWT_SECRET=$(cat "$JWT_SECRET_FILE")
    fi

    # Check if database exists
    if [ ! -f "$DB_PATH" ]; then
        print_step "User database not found - creating..."

        # Create empty database with schema
        python3 << EOF
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from glados.auth.database import UserDatabase

db = UserDatabase(Path("$DB_PATH"))
print("✓ Database created with schema")
EOF
        print_success "Database created"
    else
        print_success "User database found"
    fi

    # Check if admin user exists
    print_step "Checking for admin user..."

    ADMIN_EXISTS=$(python3 << EOF
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from glados.auth.database import UserDatabase

db = UserDatabase(Path("$DB_PATH"))
admins = [u for u in db.get_all_users() if u.is_admin]
print("yes" if admins else "no")
EOF
    )

    if [ "$ADMIN_EXISTS" == "no" ]; then
        print_warning "No admin user found - creating one now"
        echo ""
        echo "Please provide admin user details:"
        echo ""

        # Get admin credentials
        read -p "Admin username: " ADMIN_USERNAME
        read -p "Admin email: " ADMIN_EMAIL

        # Get password with confirmation
        while true; do
            read -s -p "Admin password: " ADMIN_PASSWORD
            echo ""
            read -s -p "Confirm password: " ADMIN_PASSWORD_CONFIRM
            echo ""

            if [ "$ADMIN_PASSWORD" == "$ADMIN_PASSWORD_CONFIRM" ]; then
                break
            else
                print_error "Passwords don't match. Try again."
            fi
        done

        # Create admin user
        python3 << EOF
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from glados.auth.database import UserDatabase

db = UserDatabase(Path("$DB_PATH"))
user = db.create_user(
    username="$ADMIN_USERNAME",
    email="$ADMIN_EMAIL",
    password="$ADMIN_PASSWORD",
    is_admin=True
)
print(f"✓ Admin user created: {user.username} ({user.email})")
EOF

        print_success "Admin user created successfully"
    else
        print_success "Admin user found"
    fi

    print_success "Authentication configured"
}

# Create authenticated server script
create_auth_server_script() {
    if [ "$ENABLE_AUTH" != "true" ]; then
        return
    fi

    print_step "Creating authenticated server script..."

    JWT_SECRET=$(cat "$JWT_SECRET_FILE")

    cat > "$AUTH_SERVER_SCRIPT" << 'EOFSCRIPT'
#!/usr/bin/env python3
"""
GLaDOS Server with JWT Authentication
Auto-generated by start_server.sh
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from glados import GladosConfig
from glados.core.engine import Glados
from glados.auth import UserManager, AuthenticationMiddleware
from glados.audio_io.network_io import NetworkAudioIO
from glados.ASR import get_audio_transcriber
from glados.TTS import get_speech_synthesizer

# Load configuration
config_file = "CONFIG_FILE_PLACEHOLDER"
config = GladosConfig.from_yaml(config_file)

# Create user manager
user_manager = UserManager(
    db_path=Path("DB_PATH_PLACEHOLDER"),
    secret_key="JWT_SECRET_PLACEHOLDER"
)

# Create authentication middleware
auth_middleware = AuthenticationMiddleware(
    user_manager=user_manager,
    require_auth=True
)

print("✓ Authentication middleware initialized")

# Create network audio IO with authentication
audio_io = NetworkAudioIO(
    host=config.network_host,
    port=config.network_port,
    auth_middleware=auth_middleware
)

print(f"✓ Network audio I/O initialized on {config.network_host}:{config.network_port}")
print("✓ JWT authentication: ENABLED")

# Create GLaDOS instance
glados = Glados(
    asr_model=get_audio_transcriber(config.asr_engine),
    tts_model=get_speech_synthesizer(config.voice),
    audio_io=audio_io,
    completion_url=config.completion_url,
    llm_model=config.llm_model,
    api_key=config.api_key,
    interruptible=config.interruptible,
    personality_preprompt=tuple(config.to_chat_messages()),
    config=config,
)

print("✓ GLaDOS initialized with authentication")
print("")
print("=" * 60)
print("  GLaDOS v2.1 - Multi-User Mode")
print("=" * 60)
print(f"  Config: {config_file}")
print(f"  Database: DB_PATH_PLACEHOLDER")
print(f"  Server: {config.network_host}:{config.network_port}")
print(f"  Authentication: REQUIRED")
print("=" * 60)
print("")

# Run the server
glados.run()
EOFSCRIPT

    # Replace placeholders
    sed -i "s|CONFIG_FILE_PLACEHOLDER|$CONFIG_FILE|g" "$AUTH_SERVER_SCRIPT"
    sed -i "s|DB_PATH_PLACEHOLDER|$DB_PATH|g" "$AUTH_SERVER_SCRIPT"
    sed -i "s|JWT_SECRET_PLACEHOLDER|$JWT_SECRET|g" "$AUTH_SERVER_SCRIPT"

    chmod +x "$AUTH_SERVER_SCRIPT"
    print_success "Authenticated server script created"
}

# Start RVC container
start_rvc() {
    if [ "$SKIP_RVC" == "true" ]; then
        print_warning "Skipping RVC service (disabled)"
        return
    fi

    print_step "Starting RVC voice cloning service..."

    if [ ! -d "rvc" ]; then
        print_warning "RVC directory not found - skipping"
        return
    fi

    cd rvc

    # Check if already running
    if docker compose ps | grep -q "Up"; then
        print_success "RVC service already running"
    else
        docker compose up -d
        sleep 2

        if docker compose ps | grep -q "Up"; then
            print_success "RVC service started"
        else
            print_warning "RVC service failed to start (non-critical)"
        fi
    fi

    cd "$PROJECT_ROOT"
}

# Run tests
run_tests() {
    if [ "$SKIP_TESTS" == "true" ]; then
        print_warning "Skipping tests (SKIP_TESTS=true)"
        return
    fi

    print_header "Running Tests"

    # Check if pytest is available
    if ! python -c "import pytest" 2>/dev/null; then
        print_warning "pytest not installed - skipping tests"
        return
    fi

    # Run unit tests if they exist
    if [ -d "tests/unit" ] && [ "$(ls -A tests/unit/*.py 2>/dev/null)" ]; then
        print_step "Running unit tests..."
        if pytest tests/unit -v --tb=short 2>&1 | tee /tmp/glados_test.log; then
            print_success "Unit tests passed"
        else
            print_warning "Some unit tests failed (see /tmp/glados_test.log)"
            read -p "Continue anyway? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        print_warning "No unit tests found"
    fi

    print_success "All tests completed"
}

# Check if GLaDOS is already running
check_running() {
    print_step "Checking for existing GLaDOS process..."

    if pgrep -f "glados.cli start\|server_with_auth.py" >/dev/null; then
        print_warning "GLaDOS server appears to be already running"
        echo ""
        echo "PIDs: $(pgrep -f 'glados.cli start\|server_with_auth.py')"
        echo ""
        read -p "Kill existing process and restart? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            pkill -f "glados.cli start\|server_with_auth.py"
            sleep 2
            print_success "Stopped existing GLaDOS process"
        else
            exit 0
        fi
    fi
}

# Start GLaDOS server
start_server() {
    print_header "Starting GLaDOS Server"

    # Verify config file exists
    if [ ! -f "$CONFIG_FILE" ]; then
        print_error "Config file not found: $CONFIG_FILE"
        echo "Available configs:"
        ls -1 configs/*.yaml 2>/dev/null || echo "  No config files found"
        exit 1
    fi

    print_step "Using config: $CONFIG_FILE"

    LOG_FILE="/tmp/glados_server.log"

    if [ "$ENABLE_AUTH" == "true" ]; then
        print_step "Starting GLaDOS with JWT authentication..."
        print_success "Authentication: ENABLED"

        # Start authenticated server
        nohup python "$AUTH_SERVER_SCRIPT" > "$LOG_FILE" 2>&1 &
        SERVER_PID=$!
    else
        print_step "Starting GLaDOS without authentication..."
        print_warning "Authentication: DISABLED (legacy mode)"

        # Start legacy server
        nohup python -m glados.cli start --config "$CONFIG_FILE" > "$LOG_FILE" 2>&1 &
        SERVER_PID=$!
    fi

    print_success "GLaDOS server started (PID: $SERVER_PID)"
    print_step "Waiting for server to initialize..."

    sleep 3

    # Check if process is still running
    if kill -0 $SERVER_PID 2>/dev/null; then
        print_success "Server is running!"
        echo ""
        echo "=" * 60
        echo "Server PID: $SERVER_PID"
        echo "Log file: $LOG_FILE"
        echo "Config: $CONFIG_FILE"

        if [ "$ENABLE_AUTH" == "true" ]; then
            echo "Authentication: ENABLED"
            echo "Database: $DB_PATH"
            echo ""
            echo "Client connection:"
            echo "  uv run glados tui --host localhost --port 5555 --auth-token <token>"
        else
            echo "Authentication: DISABLED"
            echo ""
            echo "Client connection:"
            echo "  uv run glados tui --host localhost --port 5555"
        fi

        echo ""
        echo "Commands:"
        echo "  Monitor logs: tail -f $LOG_FILE"
        echo "  Stop server: kill $SERVER_PID"
        echo ""

        # Save PID for later
        echo $SERVER_PID > /tmp/glados_server.pid

    else
        print_error "Server failed to start!"
        echo ""
        echo "Last 20 lines of log:"
        tail -20 "$LOG_FILE"
        exit 1
    fi
}

# Show usage
show_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Start the GLaDOS v2.1 server with JWT authentication (default) or legacy mode.

Options:
  --config FILE       Use specific config file (default: $CONFIG_FILE)
  --no-auth           Disable authentication (legacy mode)
  --skip-tests        Skip running tests
  --skip-rvc          Skip starting RVC service
  --help              Show this help message

Environment Variables:
  CONFIG_FILE         Path to config file
  SKIP_TESTS          Set to 'true' to skip tests
  SKIP_RVC            Set to 'true' to skip RVC service
  ENABLE_AUTH         Set to 'false' to disable auth

Examples:
  $0                                    # Standard startup with auth
  $0 --no-auth                          # Legacy mode without auth
  $0 --skip-tests                       # Skip tests
  $0 --config configs/custom.yaml       # Use custom config

Authentication:
  By default, the server runs with JWT authentication enabled.

  First Run:
    - Generates JWT secret automatically
    - Creates user database
    - Prompts for admin user creation

  Subsequent Runs:
    - Uses existing database and secret
    - No prompts needed

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --no-auth)
            ENABLE_AUTH="false"
            shift
            ;;
        --skip-tests)
            SKIP_TESTS="true"
            shift
            ;;
        --skip-rvc)
            SKIP_RVC="true"
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
    print_header "GLaDOS v2.1 Server Startup"
    echo "Project: $PROJECT_ROOT"
    echo "Config: $CONFIG_FILE"
    echo "Authentication: $([ "$ENABLE_AUTH" == "true" ] && echo "ENABLED" || echo "DISABLED")"
    echo ""

    check_python
    check_system_deps
    check_ollama
    setup_venv
    install_dependencies

    # Setup authentication if enabled
    if [ "$ENABLE_AUTH" == "true" ]; then
        setup_auth
        create_auth_server_script
    fi

    start_rvc
    run_tests
    check_running
    start_server

    print_header "Server Started Successfully!"

    if [ "$ENABLE_AUTH" == "true" ]; then
        print_success "GLaDOS v2.1 is running with multi-user authentication"
    else
        print_success "GLaDOS v2.1 is running in legacy mode (no auth)"
    fi

    echo ""
    echo "Next steps:"
    echo "  1. Monitor logs: tail -f /tmp/glados_server.log"

    if [ "$ENABLE_AUTH" == "true" ]; then
        echo "  2. Create users: python scripts/create_admin.py"
        echo "  3. Start client with auth token"
    else
        echo "  2. Start client: uv run glados tui"
    fi

    echo ""
}

# Run main function
main
