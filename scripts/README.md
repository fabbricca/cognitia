# Cognitia Scripts

Utility scripts for managing the Cognitia platform.

## Quick Start

### Start Core GPU Server

```bash
./scripts/start_core.sh
```

This script will:
- ✓ Check Python 3.10+ installation
- ✓ Check NVIDIA GPU availability
- ✓ Check Ollama service status
- ✓ Create virtual environment if missing
- ✓ Install all dependencies (with CUDA support)
- ✓ Start the Core FastAPI server

### Options

```bash
# Development mode with auto-reload
./scripts/start_core.sh --reload

# Custom port
./scripts/start_core.sh --port 8080

# Multiple workers (production)
./scripts/start_core.sh --workers 4

# All options
./scripts/start_core.sh --host 0.0.0.0 --port 8001 --workers 2
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COGNITIA_HOST` | `0.0.0.0` | Server bind address |
| `COGNITIA_PORT` | `8001` | Server port |
| `COGNITIA_RELOAD` | `false` | Enable auto-reload |
| `COGNITIA_WORKERS` | `1` | Number of workers |

---

## Other Scripts

### `check_health.py`
Health check utility for the API server.

```bash
python scripts/check_health.py
```

### `create_admin.py`
Create an admin user in the database.

```bash
python scripts/create_admin.py
```

### `manage_users.py`
User management utilities (list, delete, modify users).

```bash
python scripts/manage_users.py --help
```

### `migrate_add_subscriptions.py`
Database migration for subscription system.

```bash
python scripts/migrate_add_subscriptions.py
```

### `generate_icons.py`
Generate app icons from source image.

### `convert_phonemizer_onnx.py`
Convert phonemizer models to ONNX format.

### `install.py`
Legacy installation script.
