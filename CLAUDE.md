# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based system monitoring tool for Linux that provides real-time hardware metrics similar to hwinfo64. It displays CPU, GPU, memory, disk, and network information with both text and graphical interfaces. Published to PyPI as `linux-hwinfo64`.

## Development Commands

### Running the Application
```bash
uv run main.py                   # Standard monitoring mode
uv run main.py --graph           # Graph mode with historical data
uv run main.py --record          # Record metrics to CSV
uv run main.py --output file.csv # Custom CSV output file
uv run main.py --neofetch        # Display system info in neofetch-like format
```

### Code Quality
```bash
uv run ruff check .                     # Lint code (ruff is in the dev dependency group)
uv run ruff format .                    # Format code
```

### Python Environment
The project uses modern Python (>=3.10) with minimal dependencies managed via pyproject.toml and uv.lock.

## Code Architecture

### Core Components

1. **linux_hwinfo64/main.py** - Entry point and UI layer (root `main.py` is a shim for `uv run main.py`; installed command is `linux-hwinfo64`)
   - Handles command-line arguments and display modes
   - Contains two curses-based display functions:
     - `display_monitor()` - Real-time text display
     - `display_monitor_graph()` - Historical graph display
   - Manages CSV recording functionality

2. **linux_hwinfo64/system_monitor.py** - Hardware monitoring backend
   - `SystemMonitor` class handles all hardware detection and metrics
   - GPU detection logic supports both NVIDIA and AMD GPUs
   - Uses psutil for CPU/memory, subprocess calls for GPU tools

### GPU Support Architecture

The application has a sophisticated GPU detection system:

- **NVIDIA**: Uses `nvidia-smi` command-line tool
- **AMD**: Multi-layered detection approach:
  - Checks `/sys/class/drm/card*/device/vendor` for AMD vendor ID (0x1002)
  - Uses `lspci` as fallback detection
  - Reads metrics from the card's sysfs files via `_read_amd_sysfs_value()`: `mem_info_vram_*`, `gpu_busy_percent`, and the card's own `hwmon/` sensors (temp, power, fan, clock)
  - Only falls back to `rocm-smi` for VRAM when sysfs doesn't provide it
  - Never read the generic `/sys/class/hwmon` for GPU values; the first entry there can be the CPU or an NVMe drive

### Key Design Patterns

- **Graceful degradation**: Missing GPU tools don't crash the application
- **Multi-source data**: Combines multiple system interfaces for comprehensive metrics
- **Historical tracking**: Graph mode maintains 2-minute rolling history using collections.deque
- **Terminal safety**: Every curses write goes through `safe_addstr()`, never `stdscr.addstr()` directly, and `draw_graph()` skips graphs that don't fit. Direct writes past the screen edge crash with `addwstr() returned ERR` on short or resized terminals
- **Network rates**: `get_network_info()` computes per-second rates from the delta since its previous call, and only counts physical interfaces (those with `/sys/class/net/<iface>/device`) so docker/bridge/VPN traffic isn't double counted
- **Logging**: `setup_logging()` in main() logs to `$XDG_STATE_HOME/linux-hwinfo64/hw_monitor.log` (default `~/.local/state/...`), never the current directory

## Dependencies and Requirements

- **Core**: psutil and distro; ruff is a dev-only dependency
- **Build**: hatchling; CI checks the wheel contains the package and installs cleanly
- **External tools**: nvidia-smi (NVIDIA GPUs), rocm-smi (optional AMD VRAM fallback)
- **System files**: Reads various /sys and /proc files for hardware information

## CI and Releases

- `.github/workflows/python-package.yml` runs ruff, CLI smoke tests on Python 3.10-3.13, and a build job that checks the wheel contents and installs it cleanly
- `main` is protected: changes go through PRs, and `lint (3.10)`-`lint (3.13)` and `build` are required checks. If CI job names change, update the required checks or PRs will block
- To release: bump `version` in pyproject.toml (and `uv lock`) in a PR, merge, then create a GitHub Release tagged `v<version>` targeting the full commit SHA. `python-publish.yml` verifies the tag matches the version, builds, and waits for the maintainer to approve the `pypi` environment before publishing via Trusted Publishing

## Common Development Patterns

When extending hardware support:
1. Add detection logic to `SystemMonitor._detect_gpu_type()`
2. Implement vendor-specific info gathering method
3. Update display functions in linux_hwinfo64/main.py to handle new metrics
4. Add appropriate error handling and logging

GPU metrics follow a consistent pattern:
- Detection first, then attempt to gather detailed metrics
- Always provide fallback values (0 or "Unknown") when tools unavailable
- Log debug/warning messages for troubleshooting
