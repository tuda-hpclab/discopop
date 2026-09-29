---
layout: default
title: Patch generator
parent: Tools
nav_order: 3
---

# DiscoPoP patch generator
## Executable
`discopop_patch_generator`

## Purpose
Convert a set of parallel patterns obtained by the [DiscoPoP Explorer](../tools/Explorer.md) or [optimizer](../tools/Optimizer.md) into a structured set of applicable patch files.
The created patches can be applied manually or via the [DiscoPoP patch applicator](../tools/Patch_applicator.md).
A generated patch is not guaranteed to compile; [patch repair](../tools/Patch_repair.md) finds those that do not and attempts to fix them.

## Required input
- `Parallel patterns` in the form of a `JSON` file

## Output
The created patches will be stored in a folder named `.discopop/patch_generator`.
Within this folder, individual folders for each parallel pattern will be created. Their `id` will act as the folders name.
Within these inner folders, patch files for all modified `file-id` are created.
Please refer to [Filemapping](../data/Filemapping.md) for information how to interpre the used `file-ids`.

## Note
For a more detailed description of the available run-time arguments, please refer to the help string of the respective tool.
```
discopop_patch_generator --help
```
