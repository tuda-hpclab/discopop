<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# DiscoPoP MCP Server - Distribution Guide

This guide explains how to package and distribute the DiscoPoP MCP Server to end users.

## Distribution Methods

### 1. PyPI Distribution (Recommended)

**Best for**: General users, Python developers

#### Steps to publish:

```bash
# 1. Update version in pyproject.toml
# 2. Build distribution packages
pip install build
python -m build

# 3. Upload to PyPI (requires credentials)
pip install twine
python -m twine upload dist/*

# 4. Users install via:
pip install discopop_mcp_server
```

**Pros:**
- Standard Python package distribution
- Easy updates and version management
- Wide reach via PyPI

**Cons:**
- Requires PyPI account
- Users need pip/Python knowledge
- Version coordination with main DiscoPoP package

**Timeline:**
- Initial setup: ~30 minutes (register PyPI account, configure credentials)
- Per release: ~5-10 minutes

### 2. GitHub Releases

**Best for**: Users with git installed

#### Steps:

1. Create a release on GitHub with binary assets
2. Users install via:
```bash
pip install git+https://github.com/tuda-hpclab/discopop.git#subdirectory=mcp_server
```

Or pin to specific version:
```bash
pip install git+https://github.com/tuda-hpclab/discopop.git@v0.1.0#subdirectory=mcp_server
```

**Pros:**
- No external account needed
- Version control integrated
- Easy to maintain with main project

**Cons:**
- Requires git installation
- Slower than PyPI
- Less discoverable

### 3. Bundled Binary (PyInstaller)

**Best for**: Non-technical users, air-gapped environments

#### Build steps:

```bash
# Install PyInstaller
pip install pyinstaller

# Create one-file executable
pyinstaller --onefile \
    --name discopop_mcp_server \
    --hidden-import=mcp \
    --collect-all=mcp \
    server.py

# Result: dist/discopop_mcp_server (Linux/macOS)
#        dist/discopop_mcp_server.exe (Windows)
```

#### Distribution:

1. Upload binaries to GitHub Releases
2. Users download and run directly (no Python needed)

**Pros:**
- No Python/pip knowledge required
- Works offline
- Single file

**Cons:**
- Larger file size (~100-150MB)
- OS-specific binaries needed
- More complex updates

**Multi-platform build (CI/CD):**

```yaml
# .github/workflows/build-mcp-server.yml
name: Build MCP Server Binaries

on:
  push:
    tags:
      - 'mcp-*'

jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        include:
          - os: ubuntu-latest
            name: linux
          - os: macos-latest
            name: macos
          - os: windows-latest
            name: windows

    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - run: |
          pip install pyinstaller
          cd mcp_server
          pyinstaller --onefile --name discopop_mcp_server server.py

      - uses: actions/upload-artifact@v3
        with:
          name: discopop_mcp_server-${{ matrix.name }}
          path: mcp_server/dist/discopop_mcp_server*
```

### 4. ~~Docker Container~~ (Not Recommended)

**Note:** Docker is not recommended for this server because:
- The server needs to access local dependencies to execute user code
- Containerization would isolate it from the user's local environment
- Local deployment is more flexible and efficient
- Users typically run this on their development machines where Docker adds unnecessary complexity

### 5. Conda Distribution

**Best for**: Data science/ML community

#### Publish to conda-forge:

1. Create feedstock repository
2. Submit PR to [conda-forge](https://conda-forge.org/)
3. Users install via: `conda install -c conda-forge discopop_mcp_server`

**Pros:**
- Reaches conda users
- Cross-platform
- Dependency resolution

**Cons:**
- Longer approval process
- Maintains separate package

### 6. Integrated with DiscoPoP Release

**Best for**: Single unified distribution

Include MCP server in main DiscoPoP package:

```bash
# In main DiscoPoP pyproject.toml
[project]
dependencies = [
    "discopop-profiler>=0.0.1",
    "discopop-library>=0.0.1",
    "discopop-explorer>=0.0.1",
    "discopop_mcp_server>=0.0.1",  # Include MCP
]

# Users get it automatically:
pip install discopop
```

**Pros:**
- Single package installation
- Unified versioning
- Simpler for users

**Cons:**
- Adds dependency to main package
- Can't update independently
- Users get it even if they don't need it

## Recommended Strategy

For DiscoPoP, I recommend a **phased approach**:

### Phase 1: Initial Release (Now)
1. Start with GitHub releases (source distribution)
2. Document installation in [INSTALLATION.md](INSTALLATION.md)
3. Push to PyPI once stable

### Phase 2: Mature Release (1-2 months)
1. PyPI as primary distribution
2. Bundled binaries for non-technical users (optional)
3. Optional: Pre-built executables via PyInstaller for Windows/macOS/Linux

### Phase 3: Integration (Future)
1. Optional: Include in main DiscoPoP package
2. Conda-forge if sufficient demand

## Version Management

### Versioning scheme:

Follow semantic versioning: `MAJOR.MINOR.PATCH`

```
0.0.1a1 - Alpha (current)
0.0.1b1 - Beta
0.0.1   - Stable release
0.1.0   - New features
1.0.0   - Major release
```

### Update strategy:

```bash
# In mcp_server/pyproject.toml
version = "0.1.0"

# In mcp_server/__init__.py
__version__ = "0.1.0"

# Create git tag
git tag -a mcp-server-0.1.0 -m "Release DiscoPoP MCP Server 0.1.0"
git push origin mcp-server-0.1.0

# Build and publish
python -m build
python -m twine upload dist/*
```

## Publishing to PyPI

### One-time setup:

1. Create PyPI account: https://pypi.org/account/register/
2. Create API token in account settings
3. Create `~/.pypirc`:
```ini
[distutils]
index-servers = pypi

[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = pypi-AgEIcHlwaS5vcmc...
```

### Per-release:

```bash
# 1. Update version
vim mcp_server/pyproject.toml
vim mcp_server/__init__.py

# 2. Build
cd mcp_server
python -m build

# 3. Publish
python -m twine upload dist/*

# 4. Tag release
git tag -a mcp-server-0.1.0 -m "Release"
git push --tags
```

## Documentation for Users

Provide comprehensive documentation for each distribution method:

1. **[INSTALLATION.md](INSTALLATION.md)** - How to install
2. **[CLAUDE_INTEGRATION.md](CLAUDE_INTEGRATION.md)** - How to use with Claude
3. **[README.md](README.md)** - Features and usage
4. **Quick start** - In each release notes

### Example release notes:

```markdown
# DiscoPoP MCP Server v0.1.0

## Installation

### Via PyPI (Recommended)
\`\`\`bash
pip install discopop_mcp_server==0.1.0
discopop_mcp_server --help
\`\`\`

### Via Source
\`\`\`bash
pip install git+https://github.com/tuda-hpclab/discopop.git#subdirectory=mcp_server
\`\`\`

## Features
- Retrieve execution configurations
- Retrieve execution results
- Full logging support

## Changes
- Initial release
- Basic tool support
- Full documentation
```

## Checklist for Release

- [ ] Bump version in `pyproject.toml` and `__init__.py`
- [ ] Update [CHANGELOG.md](CHANGELOG.md) if exists
- [ ] Run tests: `pytest mcp_server/`
- [ ] Run type check: `mypy mcp_server/`
- [ ] Build: `python -m build`
- [ ] Test install: `pip install dist/discopop_mcp_server-*.whl`
- [ ] Create git tag: `git tag -a mcp-server-X.Y.Z`
- [ ] Push: `git push && git push --tags`
- [ ] Publish to PyPI: `python -m twine upload dist/*`
- [ ] Create GitHub release with notes
- [ ] Update documentation
- [ ] Announce in release notes

## Maintaining Multiple Distribution Channels

Once you have multiple channels, keep them in sync:

| Channel | Command | Frequency |
|---------|---------|-----------|
| PyPI | `twine upload` | Every release |
| GitHub | Create release | Every release |
| Docker | `docker push` | Every release |
| Conda-forge | PR to feedstock | As needed |

## Monitoring

Track distribution stats:

```bash
# PyPI stats
curl -s https://pypistats.org/api/packages/discopop_mcp_server/overall | jq .

# GitHub releases
gh release list --repo tuda-hpclab/discopop | grep mcp

# Docker pulls (if using Docker Hub)
# https://hub.docker.com/r/discopoptool/mcp-server/
```

## Support

Maintain a support table:

| Installation Method | Support Level | Maintenance |
|-------------------|---------------|-------------|
| PyPI | ✅ Full | Updates via pip |
| Source/GitHub | ✅ Full | Self-serve |
| Bundled binary | ✅ Full | CI/CD builds |
| Conda | ⚠️ Limited | Conda-forge team |

## See Also

- [INSTALLATION.md](INSTALLATION.md)
- [CLAUDE_INTEGRATION.md](CLAUDE_INTEGRATION.md)
- [README.md](README.md)
- [PyPI Help](https://pypi.org/help/)
- [setuptools Documentation](https://setuptools.pypa.io/)
