---
layout: default
title: File mapping
parent: Data
nav_order: 2
---

# File mapping

The instrumentation pass creates the file `.discopop/FileMapping.txt` (more precisely `$DOT_DISCOPOP/FileMapping.txt`, `DOT_DISCOPOP` defaults to `.discopop`, see [Environment variables](../setup/environment_variables.md)). It assigns an id to every source file the pass encounters. All other files refer to source files by these ids, for example the node ids `1:7` (`<file id>:<node id>`) and the line ids `1:20` (`<file id>:<line>`).

Each line has the format `<file id><TAB><absolute file path>`:

```text
1	/home/user/dp_example/example.cpp
```

- ids start at 1
- the id 0 stands for code outside of the instrumentation scope (`DP_PROJECT_ROOT_DIR`, default `/`) or in one of its excluded directories (`DP_PROJECT_EXCLUDE_DIRS`); such code gets no file id
- every compiled module appends the files it encounters, so the ids are the same in all translation units of a project; a file that is already listed keeps its id

Remove `.discopop` before you instrument a project again, otherwise stale entries remain.

## Usage

Use the file to map the file ids in `Data.xml`, `dynamic_dependencies.txt`, `patterns.json` and other files to source files. In Python, `load_file_mapping(fmap_path) -> Dict[int, Path]` in `library/discopop_library/PathManagement/PathManagement.py` reads the file; it warns about listed files that do not exist.

## line_mapping.json

`.discopop/line_mapping.json` is created when the explorer sets up the `.discopop` directory. It tracks how lines of the source files move when patches insert pragmas. The format is `{"<file id>": {"<original line>": <current line>}}`; initially every line maps to itself:

```json
{"1": {"1": 1, "2": 2, "3": 3, "...": "..."}}
```

The [patch applicator](../tools/Patch_applicator.md) and the other patch tools update it.
