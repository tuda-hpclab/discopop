---
layout: default
title: Installation
parent: Setup
nav_order: 1
---

# Installation

DiscoPoP consists of seven Python packages. The profiler (`discopop-profiler`) and the hotspot detection (`discopop-hotspot-detection`) contain C++ code that is built on your machine during the installation, so the build prerequisites below have to be installed first. All packages are installed into a Python virtual environment.

1. TOC
{:toc}

## Prerequisites

| Requirement | Version | Used for |
|---|---|---|
| LLVM and clang (development packages) | 19, 20, 21 or 22 | the profiler and the hotspot detection build an LLVM pass |
| `libclang-<version>-dev` (optional) | same as clang | builds the AST export plugin, which makes the instrumentation of template heavy projects much faster; without it the profiler works the same, see [Instrumentation](../tools/Instrumentation.md#ast-export-plugin) |
| Python (with `venv` and `pip`) | 3.11 or newer | all tools |
| CMake | 3.28 or newer | building the C++ code |
| C++20 compiler, `make` | | building the C++ code |
| Boost headers | any recent version | the profiler uses header-only Boost libraries |
| `python3-tk` and a display | | the GUI (`discopop_gui`) |
| `git` | | checkout of the repository |

If no Boost installation is found, the build downloads Boost with CMake's FetchContent. This needs network access during the build.

### Debian and Ubuntu

```bash
sudo apt install python3 python3-pip python3-venv python3-tk build-essential cmake git llvm-19-dev clang-19 clang-tools-19 libomp-19-dev libboost-dev
```

Replace `19` with `20`, `21` or `22` for another LLVM release. Ubuntu 24.04 packages LLVM 19 and 20, Debian 13 packages LLVM 19 and 22. Other releases are available from [apt.llvm.org](https://apt.llvm.org).

### Versions tested in CI

The continuous integration builds and tests DiscoPoP on these combinations (see `.github/workflows/ci.yml`):

| Distribution | LLVM | Python |
|---|---|---|
| Ubuntu 24.04 | 19 | 3.11 |
| Ubuntu 24.04 | 20 | 3.12 |
| Debian 13 | 21 (from apt.llvm.org) | 3.13 |
| Debian 13 | 22 | 3.13 |

### Arch Linux and macOS

{: .note }
The following routes are not tested in CI.

Arch-based distributions (`pacman`):

```bash
sudo pacman -S python python-pip tk base-devel cmake git llvm clang openmp boost
```

Arch ships the latest LLVM release. DiscoPoP supports LLVM 19&ndash;22 only, so install `llvm19`, `clang19` and `openmp` from the AUR if the packaged release is newer.

macOS (Homebrew):

```bash
brew install python python-tk llvm@21 libomp boost ninja
export PATH="$(brew --prefix llvm@21)/bin:$PATH"
export LDFLAGS="-L$(brew --prefix llvm@21)/lib"
export CPPFLAGS="-I$(brew --prefix llvm@21)/include"
```

Homebrew installs LLVM keg-only, which is why the three `export` lines are needed. Use `llvm@19`, `llvm@20` or `llvm@22` for another release.

## Install from PyPI

Use this route to run DiscoPoP on your own programs.

```bash
python3 -m venv venv
source venv/bin/activate
pip install discopop
```

The package `discopop` installs all other packages as dependencies: the profiler, the explorer, the library (with the project manager, the GUI and the other tools), the hotspot detection and the MCP server. The build of the profiler takes a few minutes.

{: .note }
Activate the virtual environment (`source venv/bin/activate`) in every new shell before you use DiscoPoP. The commands `discopop_cxx`, `discopop_explorer`, `discopop_gui` and the others are installed into `venv/bin`.

## Install from a checkout

Use this route to work on the code of DiscoPoP or to use the current development state. The development happens on the branch `new_explorer` (see [How to contribute](../How_to_contribute.md)).

```bash
git clone https://github.com/tuda-hpclab/discopop.git
cd discopop
make
source venv/bin/activate
```

`make` (target `install`) does the following:

1. creates the virtual environment `venv` in the root of the checkout (`python3 -m venv venv`),
2. installs all seven packages from the checkout into it. The profiler and the hotspot detection are installed as regular packages, the explorer, the library, the GUI package, the MCP server and the root package `discopop` in editable mode, so that changes to their Python sources take effect immediately.

The first `make` takes about six minutes, as it builds the profiler and the hotspot detection.

### Manual installation

The following commands are equivalent to `make`, apart from the editable installs:

```bash
python3 -m venv venv
venv/bin/python -m pip install . ./profiler ./explorer ./library ./GUI ./hotspot_detection ./mcp_server
source venv/bin/activate
```

{: .important }
Pass all package paths in **one** `pip install` command. Otherwise pip resolves the dependencies of the root package from PyPI and installs the released packages instead of the ones from your checkout.
Never use `-e` for `./profiler` and `./hotspot_detection`: the compiler wrappers locate the built `LLVMDiscoPoP.so` relative to the installed package, which an editable install breaks.

To pass CMake options to the build of the profiler, see [Build options](./build_options.md#options-for-the-pip-build). For the tools used by contributors (formatting, type checking, tests), install `requirements-dev.txt` as described in [How to contribute](../How_to_contribute.md).

### Remove the checkout installation

`make veryclean` deletes the virtual environment `venv` and the directory `build`.

## Verify the installation

The repository contains a small example program in `example/`. Work on a copy, so that the profiling data does not end up in the source tree:

```bash
cp -r example /tmp/dp_example
cd /tmp/dp_example
discopop_cxx example.cpp -o a.out
./a.out
cd .discopop
discopop_explorer
ls patch_generator/*/*.patch
```

In a PyPI installation there is no checkout, so copy `example.cpp` from the [repository](https://github.com/tuda-hpclab/discopop/tree/master/example) instead.

- `discopop_cxx` compiles the program and instruments it with the DiscoPoP LLVM pass. It creates the directory `.discopop`.
- `./a.out` runs the instrumented program. It prints `Outputting instrumentation results... done` when the profiling data has been written.
- `discopop_explorer` analyzes the profiling data. For the example it reports two suggestions, `0` (a do-all loop) and `1` (a reduction), and the patches `patch_generator/0/1.patch` and `patch_generator/1/1.patch` exist afterwards.

If this works, the installation is complete. The [command line walk-through](../examples/walk_through.md) continues with these results. To check the GUI, run `discopop_gui` in an empty directory (a display is required).

## Register the MCP server (optional)

The MCP server lets AI assistants run DiscoPoP. After the installation, register it with your assistant:

```bash
discopop_mcp_server --setup claude_code
```

`opencode` is supported as well (`--setup opencode`). The server calls the DiscoPoP tools by name, so register it from the activated virtual environment. See [MCP server](../tools/MCP_server.md) for details.

## Uninstall

Delete the virtual environment, or uninstall the packages from it:

```bash
venv/bin/python -m pip uninstall -y discopop discopop-profiler discopop-explorer discopop-library discopop-gui discopop-hotspot-detection discopop-mcp-server
```
