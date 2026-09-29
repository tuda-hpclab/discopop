---
layout: default
title: Visual Studio Code Extension
parent: Setup
nav_order: 2
---

# How to Setup The Visual Studio Code Extension for DiscoPoP

Using the DiscoPoP VS Code extension is the recommended way to get started using DiscoPoP, especially when your projects use the CMake build system.

## Prerequisites

- [DiscoPoP](https://github.com/tuda-hpclab/discopop) is installed: Check out [How to install DiscoPoP](./discopop.md) before following this guide.
- The [HotspotDetection](https://github.com/discopop-project/Hotspot-Detection) is installed. The setup procedure is the same as for DiscoPoP.
- [VS Code](https://code.visualstudio.com/) is installed.
- OS: Linux or Windows with [WSL](https://code.visualstudio.com/docs/remote/wsl-tutorial) are supported.

## Setup

Install the [DiscoPoP extension](https://marketplace.visualstudio.com/items?itemName=TUDarmstadt-LaboratoryforParallelProgramming.discopop) from the VS Code marketplace.

## Next Steps

You can get started to use the VS Code extension right away. Check out the [Example Walkthrough](../examples/walk_through_gui.md) for more information.


## Troubleshooting: Common Issues

If you have any trouble to setup the tools, the following tips might help you. If you still run into problems during setup or usage, please [create an issue on github](https://github.com/discopop-project/discopop-gui-vscode/issues).

- Make sure to install compatible versions of DiscoPoP, the HotspotDetection and the VS Code extension. The latest released versions of all tools should always be compatible.
- DiscoPoP must be build within `<path/to/discopop>/build`. Builds in other locations are currently not supported. In the extension settings: provide `<path/to/discopop>`, **not** `<path/to/discopop>/build` in the 'DiscoPoP Root setting.
- The HotspotDetection must be built within `<path/to/hotspot-detection>/build`. Builds in other locations are currently not supported. In the extension settings: provide `<path/to/hotspot-detection>`, **not** `<path/to/hotspot-detection>/build` in the 'Hotspot Detection Root' setting.
