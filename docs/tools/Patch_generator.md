---
layout: default
title: Patch generator
parent: Tools
nav_order: 6
---

# Patch generator
## Executable
`discopop_patch_generator`

## Purpose
Convert the parallel patterns identified by the [explorer](Explorer.md) into a structured set of patch files.
You can apply the patches manually or with the [patch applicator](Patch_applicator.md).
A generated patch is not guaranteed to compile; [patch repair](Patch_repair.md) finds those that do not and attempts to fix them.

The [explorer](Explorer.md) runs the patch generator itself after the pattern detection, so you only call it directly to regenerate patches or to generate them for patterns from another file.

## Required input
Run the tool from inside the `.discopop` directory.
- `explorer/patterns.json`, created by the [explorer](Explorer.md). Patterns of another file (for example `optimizer/patterns.json` of the [optimizer](Optimizer.md)) are only added with `-a`.
- `FileMapping.txt` (the tool stops with an error if it is missing)

## Output
The patches are stored in `patch_generator/` (inside `.discopop`).
For each parallel pattern, a folder named after the pattern `id` is created. It contains one patch file `<file id>.patch` for every modified file.
See [File mapping](../data/Filemapping.md) for how to interpret the file ids.


## Example
```bash
cd .discopop && discopop_patch_generator
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `-v`, `--verbose` | off | Enable verbose output. |
| `-a`, `--add-from-json <file>` | none | Add the patches specified in the given `patterns.json` file, e.g. `optimizer/patterns.json`. |
| `--log` | `WARNING` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--write-log` | off | Write a log file. |

Benchmarking options (may change or be removed):

| Option | Description |
|--------|-------------|
| `--only-optimizer-output-patterns` | Only generate code for the `optimizer_output` patterns. |
| `--only-maximum-id-pattern` | Only generate code for the pattern with the highest id. |
