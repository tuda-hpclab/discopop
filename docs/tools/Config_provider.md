---
layout: default
title: Config provider
parent: Tools
nav_order: 7
---

# DiscoPoP config provider
## Executable
`discopop_config_provider`

## Purpose
The config provider acts a simple and globally accessible way to retrieve information regarding the local DiscoPoP installation.
Values which can obtained via the config provider are for example the paths to the `discopop build directory`, the `discopop source directory`, or the `llvm binary directory`.


## Output
The requested values are simply returned in the form of a string if the python module is imported, or printed to `stdout` in case of a standalone invokation.

## Note
For a more detailed description of the available run-time arguments, please refer to the help string of the respective tool.
```
discopop_config_provider --help
```
