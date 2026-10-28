---
layout: default
title: Patch applicator
parent: Tools
nav_order: 7
---

# Patch applicator
## Executable
`discopop_patch_applicator`

## Purpose
Apply, roll back, clear and restore parallelization suggestions in the form of the patch files created by the [patch generator](Patch_generator.md). The applicator keeps track of the applied suggestions, so you can undo them one by one or all at once.

## Required input
Run the tool from inside the `.discopop` directory.
- `FileMapping.txt` and the `patch_generator/` folder (created by the [explorer](Explorer.md))
- One action (see the options) and, for `-a` and `-r`, the suggestion ids

## Output
The patches modify the source files named in `FileMapping.txt` in place. A suggestion is applied completely or not at all: if one of its files cannot be patched, the files already patched are restored.

The applicator keeps its state in `patch_applicator/` (inside `.discopop`):

| File | Contents |
|------|----------|
| `applied_suggestions.json` | The ids of the applied suggestions. |
| `applied_suggestions.json.save` | The list saved by `-C`, restored by `-L`. |
| `application_result.json` | The outcome of the last `-a` call (`requested`, `applied`, `failed`, `unknown`, `already_applied`). Removed by `-C`. |

The exit code is `0` if everything requested was applied, `1` if nothing could be applied and `2` if only some suggestions were applied. A rollback without suggestion ids ends with `3` (nothing to roll back).

## Example
Run the [explorer](Explorer.md) on `example/example.cpp` first. Then:
```bash
cd .discopop
discopop_patch_applicator -a 0 1   # apply suggestions 0 and 1
discopop_patch_applicator -l       # list the applied suggestions
discopop_patch_applicator -r 1     # roll back suggestion 1
discopop_patch_applicator -C       # reset the code to its original state (saves the list)
discopop_patch_applicator -L       # apply the saved suggestions again
discopop_patch_applicator -C       # reset again
```

{: .note }
`-C` overwrites an earlier save. Calling it twice in a row saves an empty list, so a following `-L` restores nothing.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `-a`, `--apply <id ...>` | none | Apply the suggestions with the given ids. Suggestions that are already applied are skipped. |
| `-r`, `--rollback <id ...>` | none | Roll back the suggestions with the given ids. |
| `-C`, `--clear` | off | Reset the code to its original state by rolling back all applied suggestions. The list of applied suggestions is saved for `-L`; an older save is overwritten. |
| `-L`, `--load` | off | Apply the suggestions saved by the last `-C`. |
| `-l`, `--list` | off | Print the applied suggestions. Nothing else is done. |
| `-v`, `--verbose` | off | Enable verbose output. |
| `--log` | `WARNING` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--write-log` | off | Write a log file. |

Only one action is executed per call, in the order `-a`, `-r`, `-C`, `-L`, `-l`.

Rolling back or clearing only works while the patched files still match the patches. If you edited a patched file by hand, the rollback fails.

## Use from other tools
- The [autotuner](Autotuner.md) and the [project manager](Project_manager.md) apply suggestions in a copy of the project.
