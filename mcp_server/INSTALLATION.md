<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# DiscoPoP MCP Server - Installation Guide

## System Requirements

- **Python**: 3.8 or higher
- **Operating System**: Linux (primary), macOS, or Windows
- **Memory**: Minimal (< 100MB)
- **Disk Space**: ~50MB (including dependencies)

## Installation Methods

### Method 1: Install from PyPI (Easiest - Coming Soon)

Once published to PyPI:

```bash
pip install discopop_mcp_server
```

### Method 2: Install from Source (Current)

```bash
# Clone the repository
git clone https://github.com/tuda-hpclab/discopop.git
cd discopop/mcp_server

# Install in development mode
pip install -e .
```

For development (including testing tools):
```bash
pip install -e ".[dev]"
```

### Method 3: Install from URL

```bash
pip install git+https://github.com/tuda-hpclab/discopop.git#subdirectory=mcp_server
```

### Method 4: Manual Installation (Without pip)

If you prefer not to use pip:

1. Download the repository:
```bash
git clone https://github.com/tuda-hpclab/discopop.git
```

2. Install dependencies:
```bash
pip install mcp
# Optional: for SSE support
pip install starlette uvicorn
```

3. Run directly:
```bash
cd discopop/mcp_server
python3 server.py --debug
```

## Dependency Installation

The server requires the `mcp` package. Installation methods:

### Standard pip

```bash
pip install mcp
```

### From conda

```bash
conda install -c conda-forge mcp
```

### All dependencies

The `pyproject.toml` includes:
- **Required**: `mcp>=0.1.0`
- **Optional (Development)**: `pytest>=7.0`, `pytest-asyncio>=0.21.0`, `mypy`, `black`

## Verification

After installation, verify everything works:

```bash
# Test 1: Check command is available
discopop_mcp_server --help

# Test 2: Run with debug
discopop_mcp_server --debug

# Test 3: Verify setup (if configured with Claude Code)
discopop_mcp_server --status
```

## Python Virtual Environment Setup (Recommended)

Using a virtual environment is recommended to avoid dependency conflicts:

### Using venv (Python 3.8+)

```bash
# Create virtual environment
python3 -m venv mcp_venv

# Activate it
# On macOS/Linux:
source mcp_venv/bin/activate
# On Windows:
mcp_venv\Scripts\activate

# Install the server
pip install git+https://github.com/tuda-hpclab/discopop.git#subdirectory=mcp_server
```

### Using conda

```bash
# Create environment
conda create -n discopop-mcp python=3.11

# Activate it
conda activate discopop-mcp

# Install the server
pip install git+https://github.com/tuda-hpclab/discopop.git#subdirectory=mcp_server
```

## Integration with Claude Code

After installation, configure Claude Code to use the server.

### Automated Setup (Recommended)

Use the built-in setup flag for easy configuration:

```bash
# Setup Claude Code integration
discopop_mcp_server --setup claude_code

# Verify configuration
discopop_mcp_server --verify claude_code

# Check status
discopop_mcp_server --status
```

For detailed setup options, see [SETUP_GUIDE.md](SETUP_GUIDE.md).

### Manual Configuration

Alternatively, configure manually. See [CLAUDE_INTEGRATION.md](CLAUDE_INTEGRATION.md) for detailed instructions.

1. Create the configuration directory:

   ```bash
   mkdir -p ~/.claude
   ```

2. Edit `~/.claude/settings.json` and add:

   ```json
   {
     "mcpServers": {
       "discopop": {
         "command": "discopop_mcp_server",
         "args": ["--debug"]
       }
     }
   }
   ```

3. Verify the server starts:

   ```bash
   discopop_mcp_server --debug
   ```

## Troubleshooting Installation

### Error: "No module named 'mcp'"

**Cause**: MCP package not installed

**Solution**:
```bash
pip install mcp
```

Or install the server with development dependencies:
```bash
pip install -e ".[dev]"
```

### Error: "command not found: discopop_mcp_server"

**Cause**: Command not in PATH

**Solutions**:
1. Ensure pip install completed successfully
2. Check Python environment:
```bash
which python3
python3 -m pip --version
```
3. Try running with full path:
```bash
python3 -m server --debug
```
4. Install to user path:
```bash
pip install --user discopop_mcp_server
```

### Error: "ImportError" on macOS M1/M2

**Cause**: Binary compatibility issues

**Solution**:
```bash
# Create native Python environment
conda create -n discopop-mcp python=3.11
conda activate discopop-mcp
pip install git+https://github.com/tuda-hpclab/discopop.git#subdirectory=mcp_server
```

### Python version too old

**Cause**: Using Python < 3.8

**Solution**:
```bash
# Check version
python3 --version

# Update Python or use specific version
python3.11 -m pip install discopop_mcp_server
```

## Installing with DiscoPoP

If installing the full DiscoPoP package:

```bash
cd discopop
pip install .  # Installs main package
pip install ./mcp_server  # Installs MCP server
```

## Uninstallation

```bash
pip uninstall discopop_mcp_server
```

## Upgrading

### From PyPI

```bash
pip install --upgrade discopop_mcp_server
```

### From source

```bash
cd discopop/mcp_server
git pull
pip install -e . --upgrade
```

## Development Installation

For contributing to the MCP server:

```bash
cd mcp_server

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest -v

# Type checking
python -m mypy server.py

# Code formatting
python -m black server.py
```

## Platform-Specific Notes

### Linux

Standard installation with pip works on most distributions:

```bash
sudo apt-get install python3-pip  # Debian/Ubuntu
pip3 install discopop_mcp_server
```

### macOS

Using Homebrew Python (recommended):

```bash
brew install python
pip install discopop_mcp_server
```

For Apple Silicon (M1/M2), native Python 3.9+ installation is recommended.

### Windows

Using PowerShell:

```powershell
python -m pip install discopop_mcp_server
discopop_mcp_server --help
```

Or using WSL2 (Windows Subsystem for Linux):

```bash
wsl
pip install discopop_mcp_server
discopop_mcp_server --debug
```

## Next Steps

1. [Setup with automated script](SETUP_GUIDE.md) (Recommended)
2. [Integrate with Claude manually](CLAUDE_INTEGRATION.md)
3. [Read the README](README.md)
4. [Run tests](README.md#testing)
5. [Configure for your use case](README.md#configuration)

## Getting Help

- **Installation issues**: Check the Troubleshooting section above
- **Usage questions**: See [README.md](README.md)
- **Bug reports**: https://github.com/tuda-hpclab/discopop/issues
- **Contact**: discopop@lists.parallel.informatik.tu-darmstadt.de
