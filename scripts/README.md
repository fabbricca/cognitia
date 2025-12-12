# GLaDOS Scripts

Management scripts for GLaDOS v2.0 server and client.

## Quick Start

### Start Server
```bash
./scripts/start_server.sh
```

This script will:
- ✓ Check Python 3.10+ installation
- ✓ Check system dependencies (git, docker)
- ✓ Check Ollama service
- ✓ Create/activate virtual environment
- ✓ Install all dependencies
- ✓ Start RVC voice cloning service
- ✓ Run Phase 1 tests
- ✓ Start GLaDOS server

### Start Client
```bash
./scripts/start_client.sh
```

This script will:
- ✓ Check client dependencies
- ✓ Verify server connection
- ✓ Check audio devices
- ✓ Start terminal client with voice/text support

---

## Scripts

### `start_server.sh`
**Comprehensive server startup script**

```bash
# Standard startup
./scripts/start_server.sh

# Custom config
./scripts/start_server.sh --config configs/custom.yaml

# Skip tests (faster startup)
./scripts/start_server.sh --skip-tests

# Skip RVC service
./scripts/start_server.sh --skip-rvc

# Environment variables
CONFIG_FILE=configs/debug.yaml ./scripts/start_server.sh
SKIP_TESTS=true ./scripts/start_server.sh
```

**Features:**
- Dependency validation (Python, git, docker, ollama)
- Automatic virtual environment setup
- Dependency installation from pyproject.toml
- RVC Docker container management
- Comprehensive test suite execution
- Process management (check/kill existing)
- Detailed logging to `/tmp/glados_server.log`

**Requirements:**
- Python 3.10+
- Git
- Ollama (LLM service)
- Docker & Docker Compose (optional, for RVC)

### `start_client.sh`
**Terminal client startup script**

```bash
# Connect to localhost
./scripts/start_client.sh

# Connect to remote server
./scripts/start_client.sh --server 192.168.1.100:5555

# Text-only mode (no microphone)
./scripts/start_client.sh --muted

# Environment variables
SERVER_HOST=glados.local ./scripts/start_client.sh
SERVER_PORT=6666 ./scripts/start_client.sh
```

**Features:**
- Automatic dependency installation (sounddevice, numpy)
- Server connectivity check
- Audio device enumeration
- Voice + text input support
- Graceful error handling

**Requirements:**
- Python 3.10+
- sounddevice (auto-installed)
- numpy (auto-installed)
- Audio input/output devices

---

## Utility Scripts

### `check_health.py`
Health check script for monitoring GLaDOS services.

```bash
python scripts/check_health.py
```

### `install.py`
Legacy installation script (deprecated - use `start_server.sh` instead).

### `convert_phonemizer_onnx.py`
ONNX model conversion utility for phonemizer.

---

## Archived Scripts

Old scripts moved to `scripts/archive/`:
- `full_restart.sh` - Old restart script
- `start_gpu_server.sh` - Old GPU-specific startup

These are kept for reference but superseded by `start_server.sh`.

---

## Troubleshooting

### Server won't start
```bash
# Check logs
tail -f /tmp/glados_server.log

# Check if already running
ps aux | grep glados

# Kill existing process
kill $(cat /tmp/glados_server.pid)

# Or
pkill -f "glados.cli start"
```

### Client can't connect
```bash
# Verify server is running
netstat -tuln | grep 5555

# Test connection
telnet localhost 5555

# Check firewall
sudo ufw status
```

### Dependencies fail to install
```bash
# Update pip
pip install --upgrade pip

# Clean install
rm -rf .venv
./scripts/start_server.sh

# Manual installation
pip install -e ".[cuda]"
```

### Audio issues (client)
```bash
# List audio devices
python -c "import sounddevice as sd; print(sd.query_devices())"

# Check ALSA/PulseAudio
aplay -l
pactl list sinks
```

---

## Development

### Run tests only
```bash
source .venv/bin/activate
pytest tests/unit -v
```

### Start server without tests
```bash
./scripts/start_server.sh --skip-tests
```

### Debug mode
```bash
# Start server in foreground
source .venv/bin/activate
python -m glados.cli start --config configs/glados_network_config.yaml
```

---

## Environment Variables

### Server
- `CONFIG_FILE` - Path to config file (default: `configs/glados_network_config.yaml`)
- `SKIP_TESTS` - Skip test suite (`true`/`false`)
- `SKIP_RVC` - Skip RVC service (`true`/`false`)

### Client
- `SERVER_HOST` - Server hostname (default: `localhost`)
- `SERVER_PORT` - Server port (default: `5555`)
- `MIC_MUTED` - Text-only mode (`true`/`false`)

---

## Examples

### Local development
```bash
# Terminal 1: Start server
./scripts/start_server.sh

# Terminal 2: Start client
./scripts/start_client.sh
```

### Remote server
```bash
# On server machine
./scripts/start_server.sh

# On client machine
SERVER_HOST=192.168.1.100 ./scripts/start_client.sh
```

### Production deployment
```bash
# Server with custom config, skip tests
./scripts/start_server.sh \
  --config configs/production.yaml \
  --skip-tests

# Monitor
tail -f /tmp/glados_server.log
```

---

## Support

For issues, see:
- [PHASE1_COMPLETE.md](../PHASE1_COMPLETE.md) - Phase 1 testing guide
- [MIGRATION_V2.md](../MIGRATION_V2.md) - Full migration documentation
- [V2_SUMMARY.md](../V2_SUMMARY.md) - v2.0 overview

---

**GLaDOS v2.0** - Built with Phase 1 improvements
