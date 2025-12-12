# Archived Scripts

This directory contains old scripts that have been superseded by the new unified startup scripts.

## Archived Files

### `full_restart.sh`
- **Status**: Deprecated
- **Replaced by**: `../start_server.sh`
- **Reason**: New script includes comprehensive dependency checks and testing

### `start_gpu_server.sh`
- **Status**: Deprecated
- **Replaced by**: `../start_server.sh`
- **Reason**: GPU support is now automatically detected in unified script

## Migration

If you were using these scripts, update to:

```bash
# Old
./scripts/full_restart.sh

# New
./scripts/start_server.sh

# Old
./scripts/start_gpu_server.sh

# New
./scripts/start_server.sh  # Auto-detects GPU
```

---

These scripts are kept for reference only.
