<!--
 /*
 * This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */
 -->

# Reusing build trees in place (incremental builds) — feasibility and plan

Status: analysis + plan (revision 2, with the user's decisions of 2026-11-24). Nothing is implemented.
Branch `design/incremental_builds` (off `master` 2a631c4a).

## 0. Decisions (user, 2026-11-24)
1. Focus: **reuse build trees in place**. This also bounds the disk usage of large programs with many builds.
2. Opt-in per project through an **optional, separate `compile_incremental.sh`**, explained in the GUI and the docs.
3. ~~ccache on by default if installed~~ → **ccache is not pursued for now** (revised 2026-11-24, §5.4).
4. Copies must **leave out configured build directories**. Avoid copies altogether where that is possible
   (§5.6).
5. **One tree per compilation mode** (`seq`, `par`, `dp`, `hd`) and per build role (normal / validation),
   so that reuse rates are high. Restrict or configure this in the GUI and on the CLI.
6. The design must generalize to other codes, not be fitted to relearn. It is checked against LULESH,
   miniFE and Kripke (local), and relearn (gh1).
7. The **evolutionary search compiles its candidates one after the other**, like every other strategy (one `par`
   slot is enough, no slot pool).
8. When the incremental build rebuilt nothing although sources changed, it **falls back to a full build**.
9. A compilation that failed with a compile error leaves the tree `failed`, and the next build is incremental
   again; interrupted / killed / timed out ones leave it `dirty`. A failing `compile_incremental.sh` that has
   already compiled the tree in the same environment is not followed by a full build (the error is in the code).

## 1. What happens today

### Project manager
- A build is a full copy of the project (`configurations/copying.py:128`, `shutil.copytree`) into
  `<project>_discopop_builds/<build_id>`, the suggestions applied, then `compile.sh`
  (`configurations/building.py:150 ensure_build`).
- A build is **reused as a whole** if its fingerprint matches (`builds.py:356 compute_fingerprint`; parts:
  `sources`, `compile_script`, `settings`, `project_directories`, `configuration`, `toolchain`, `included_sources`,
  `callpath_pruning` (dp), `openmp` (dp/hd), `patches`). If any part differs, the tree is deleted and copied
  and compiled from scratch (`copying.py:118-128`).
- The suggestions are part of the identity (`BuildKey.build_id` = `<config>_<mode>_s<sha1>`, `builds.py:80`):
  every suggestion set has a tree of its own (disk!) and shares nothing with the others.
- The validation build (`compile_validate.sh`) runs in the same tree and invalidates the build afterwards
  (`builds.py:743 invalidate_build`).

### Autotuner
- Does **not** use the build cache. Every candidate: `CodeConfiguration.create_copy` → `copy_configuration`
  (whole project *including* the whole `.discopop`), `apply_suggestions`, `compile_only` (`compile.sh`), run,
  `deleteFolder` (`EmpiricalAutotuning/Classes/CodeConfiguration.py:101-345`).
- The evolutionary search compiles candidates **concurrently** (`multiprocessing.Pool()`,
  `optimization/evolutionary_combination.py:799`). All other strategies run one candidate at a time.
- The **reference configuration is compiled in the user's project itself** (`Autotuner.py:168-169`:
  `CodeConfiguration(arguments.project_path, …)`). Every later candidate copy therefore carries the freshly
  configured build state of the original (experiment 2).

### Compile scripts in practice
| code | `compile.sh` | wipes its state? |
|---|---|---|
| LULESH, burkardt/md, trivial/doall (harness) | `rm -rf build; mkdir build; cd build; cmake ..; make` | yes |
| miniFE (harness) | `cd src; make clean; make -f Makefile.gnu.parameterized` | yes |
| relearn (gh1) | `cmake -S $ROOT -B $ROOT/dp_build …; cmake --build … --target relearn`; deletes `dp_build` only if its `CMakeCache.txt` belongs to another directory (it was copied) | no; it works around the copied cache itself |

Today's scripts are written for "fresh copy, build from scratch". That is why reuse has to be a script of its
own (`compile_incremental.sh`, decision 2). relearn's script shows that users already have to defend against
copied build directories (decision 4).

## 2. Experiments

All builds below compile the same sources twice: once from scratch and once incrementally after a
patch-like change (a comment appended to a file). "TUs" are the recompiled translation units (`Building` lines).

### 2.1 Times
**LULESH_SEQ** (local, clang-21 `-fopenmp`, no `CMAKE_BUILD_TYPE`, 8 cores, 5 TUs)

| step | time |
|---|---|
| configure | 0.26 s |
| full build (serial, as its `compile.sh`) | 1.01 s |
| incremental, `lulesh.cc` (where its suggestions are) | 0.33 s |
| incremental, `lulesh.h` (all TUs) | 1.00 s |

**Kripke** (local, clang-21, Release, OpenMP, `-j8`; RAJA/umpire/chai inside; 84 TUs in the inner build)

| step | time |
|---|---|
| configure (outer superbuild) | 0.5 s |
| full inner build `-j8` / `-j1` | 17.6 s / 77.5 s |
| incremental, one kernel `.cpp` | 1.7 s (1 TU) |
| incremental, `Kripke/Kernel.h` | 7.1 s (17 TUs) |

**relearn** (gh1, aarch64, 72 cores, clang-22.1.8 `-fopenmp`, `-j32`; 97 TUs, build dir 695 MB). The files are
the targets that relearn's 71 generated suggestions patch most often.

| step | time | TUs |
|---|---|---|
| copy of the project without `dp_build` and `.discopop` | 0.1 s | |
| configure (fresh, CPM cache warm) | 17.9 s | |
| full build | 72.6 s | 97 |
| **today per build: configure + full build** | **90.5 s** | |
| compile script again, nothing changed (configure + build) | 8.3 s | 1 (`relearn.cpp`: something regenerated at configure) |
| incremental, `BoxBasedRandomSubdomainAssignment.cpp` | 3.1 s | 1 |
| incremental, `BarnesHutLocationAware.cpp` | 12.6 s | 1 |
| incremental, `CombinedActivityInputBase.h` | 6.2 s | 1 |
| incremental, `Octree.h` | 58.0 s | 15 |

(clang-18 without OpenMP, same machine: configure 21.6 s + full build 85.1 s, incremental 3.8 / 14.7 / 9.0 / 66.4 s.)

Of relearn's 71 suggestions, 46 patch only `.cpp` files and **25 patch a header**.

### 2.2 Reading
- The more TUs a project has and the longer it compiles, the more an incremental build gains. A suggestion
  confined to one `.cpp` builds **7-29x faster** (relearn: 3-13 s instead of 90 s; Kripke: 1.7 s instead of
  17.6 s at `-j8` / 77 s at `-j1`). A patched header that is widely included gains little
  (relearn `Octree.h`: 58 s vs 90 s). Codes made of one TU (miniFE) and small codes (LULESH: about 1 s in total)
  gain nothing worth mentioning.
- **Configure is a large share** (relearn 18 s of 90 s), and running it again is not free (8 s,
  and it recompiled `relearn.cpp`). A `compile_incremental.sh` should normally *only build*. The docs must say so.
- The autotuner evaluates candidates that differ by one or a few suggestions (greedy, hotspot-guided, descent).
  Consecutive candidates in one tree therefore usually differ in only 1-2 files.

### 2.3 Correctness hazards (all reproduced)
1. **A configured CMake tree cannot be moved.** After `mv A B`, `make` fails with `The source directory ".../A"
   does not exist` (`CMAKE_HOME_DIRECTORY` is absolute). Depfiles, `DP_PROJECT_ROOT_DIR`, `FileMapping.txt` and
   `DOT_DISCOPOP` are absolute as well. **Reuse only works in place, in a tree with a stable path.**
2. **A copied CMake build dir silently builds the original.** `cp -a A C`, an `#error` added to
   `C/lulesh-util.cc`, `make` in `C/build` → exit 0, nothing compiled. The copied cache points at `A`, so `make`
   works on the original's build directory. A `cmake ..` in the copy stops with `CMakeCache.txt directory … is
   different`. This is latent today (masked by `rm -rf build`), and it is the reason for relearn's workaround.
3. **mtime trap.** Restoring an earlier version of a file with `cp -p` (= `copy2` / `copytree`) keeps the old
   mtime → `make` recompiles **nothing**, and the binary keeps the modified object.
4. **Superbuilds do not propagate source changes.** Kripke's top-level CMake builds the code as an
   `ExternalProject` without `BUILD_ALWAYS`. After a source change, `cmake --build build` exits 0, recompiles
   nothing and leaves a **stale `kripke.exe`**. The inner build (`build/kripke-build`) has to be built instead.
   This is general: any build that only checks whether a sub-step was already done (ExternalProject, stamp
   files, autotools `config.status`, hand-written Makefiles without header dependencies) can produce a stale
   binary. A user's incremental script can be wrong in ways the project manager cannot see; §5.5 limits the damage.

## 3. Feasibility per mode

| mode | in-place reuse | notes |
|---|---|---|
| `par` | yes | the main use case: autotuner candidates and suggestion builds differ only in applied patches |
| `seq` | yes | re-used after source edits by the user; a tree of its own (decision 5) |
| `dp` | yes, **full rebuild in the tree until verified** | the tree can be kept (disk, configure state), but an *incremental* instrumented build is unverified: `FileMapping.txt` ids are assigned the first time a file is seen and kept in the file (`share/lib/DPUtils.cpp:251-300`), so they would probably stay stable. Not checked: the static data per TU, the CU / loop id spaces, `ast_dump.json`, and the instrumented-directory lists when only some TUs are recompiled. Until a test proves it, a `dp` build runs `compile.sh` (full) even if `compile_incremental.sh` exists |
| `hd` | same as `dp` | region / file id counters of the hotspot pass |

"Full rebuild in the tree" still saves the copy and the disk space of a second tree. Whether it saves
configure time depends on the script: `compile.sh` usually wipes everything.

## 4. Options considered

- **A. ccache with fresh copies.** Decides by content: safe against hazards 3 and 4, needs no script
  contract, and works with concurrent copies at new paths (with `CCACHE_BASEDIR` / `CCACHE_NOHASHDIR`).
  Configure and link are not cached, so relearn would still pay ≥ 18 s per build, plus the copy and its disk
  space. Not pursued for now (decision 3).
- **B. Persistent in-place trees with content sync + `compile_incremental.sh`.** The main mechanism
  (decision 1). Saves configure, link of unchanged targets and all unchanged TUs, and bounds the disk usage
  to one tree per mode and role.
- **C. Out-of-source build directories next to a shared source tree.** Not general (patched sources differ per
  candidate; in-source builds and Makefile projects write next to the sources). Only the special case of §5.6.

## 5. Design

### 5.1 Build trees ("slots")
- A **slot** is a build tree with a stable path that is kept and re-synced:
  `<project>_discopop_builds/<owner>_<mode>[_validate]`, where `<owner>` is the configuration that owns the
  build (`build_sharing.build_owner_of`), `<mode>` ∈ {seq, par, dp, hd}, `_validate` is the tree of
  `compile_validate.sh` (decision 5).
- The `BuildKey` of a slot no longer contains the suggestions. The manifest records the slot's **content
  state**: the source entries it was synced to, the applied suggestion set, the patch fingerprint, and the
  state (`clean` | `syncing` | `building` | `dirty` | `failed`).
- The fingerprint is split:
  - **environment part**: `compile_script` (resp. the incremental script), `settings`, `project_directories`,
    `configuration`, `toolchain`, `callpath_pruning`, `openmp`. If it
    differs → **reset** (the slot is emptied and synced from scratch, then `compile.sh`).
  - **content part**: `sources`, `included_sources`, `patches` + applied set. If only this differs →
    **sync + incremental build** if a `compile_incremental.sh` exists and the mode allows it (§3), otherwise
    sync + `compile.sh` in the slot.
  - Nothing differs → reuse (as today).
- `compute_fingerprint` already returns the parts separately (`builds.py:356`). The split is a classification
  of the existing keys, plus a test that every new part is classified (so a new part can never silently count
  as "content").

### 5.2 Content sync instead of copying (and instead of patch/rollback on the current state)
Rolling back the previous suggestion set and applying the new one would depend on the applicator state in the
tree (`.discopop/patch_applicator/applied_suggestions.json`, `.discopop/line_mapping.json`, both updated by every
apply / rollback, `PatchApplicator/apply.py:141`, `LineMapping/save.py`) and on the order. Instead:
1. Prepare the **target content** in a scratch directory: for every file the old *or* the new set patches, the
   pristine project version; then the new set applied there with a fresh applicator state (as in a copy today).
2. Compare with the slot: the project files changed since the last sync (source entries recorded in the
   manifest vs. now, `BuildFiles.sources`, `builds.py:109`), plus the files of step 1.
3. **Write only files whose content differs**, with the **current mtime** (hazard 3). Leave identical files
   untouched (keeps their objects and the build system's view of them).
4. Mirror deletions and additions (a deleted source must also disappear from the slot, since globs may pick it up).
5. Replace the slot's applicator state (`applied_suggestions.json`, `line_mapping.json`, application result) with
   the scratch state, and rewrite `FileMapping.txt` paths as `copy_configuration` does.
6. The manifest says `syncing` while this runs. An interrupted sync leaves `syncing`, and the next use resets the slot.

The initial fill of a slot is the same sync against an empty directory, and it **leaves out configured build
directories** (§5.3).

### 5.3 Leaving configured build directories out of copies (decision 4)
This applies to every copy: slots, today's builds, the autotuner copies, and `--inplace`-free runs.
- Leave out every directory that contains a `CMakeCache.txt`, and every directory named in a project setting
  `copy_exclude` (default: empty; for build systems that leave no marker). Also leave out the usual markers of
  other generators where they are unambiguous: `CMakeFiles/`, `meson-private/` (whole build dir),
  `config.status` + `Makefile` of an autotools *out-of-source* build directory (not in-source: there they sit
  next to the sources). Generic rule: **a directory is a build directory if it contains a build system's
  cache file**. The list lives in one function with tests.
- Report what was left out (once per build, in the console), so a user whose script relies on a pre-built
  directory (unusual) sees why the build now takes longer.
- `.discopop` data is left out as today (`DATA_LEFT_OUT_OF_BUILDS`). The autotuner copies get the same
  treatment (today they copy everything).

### 5.4 Compiler cache — deferred (decision 3)
Not part of this plan. The notes below are kept for a later decision.
- Was proposed: on by default if `ccache` is on the `PATH`. Project setting `.discopop/project/compiler_cache.json`
  (`{"enabled": "auto" | true | false, "max_size": "…"}`), CLI `--compiler-cache/--no-compiler-cache` on the
  project manager and the autotuner, GUI *Build* stage → Advanced.
- Only for **`seq` / `par`** compilations. `discopop_cc` / `discopop_hotspot_cc` have side effects (FileMapping,
  static data, AST dump) that a cache hit would skip, so `dp` / `hd` never use it.
- Implementation: `CC` / `CXX` point to generated wrapper scripts (`exec ccache <resolved compiler> "$@"`),
  not `CC="ccache clang"`, since scripts quote `"$CC"`. `CCACHE_DIR=<project>_discopop_builds/.ccache`
  (deleted together with the builds), `CCACHE_BASEDIR=<tree root>`, `CCACHE_NOHASHDIR=1`, `CCACHE_MAXSIZE`.
  The toolchain fingerprint keeps hashing the real compiler.
- Downsides checked:
  - Only a cache-dir size (bounded, deletable).
  - An unusual compiler wrapper path in CMake caches. CMake identifies the compiler by running it, so this works.
  - Content hashing cannot return a wrong object for the same input.
  - With slots it mostly helps after a *reset* (an environment change back and forth, e.g. a settings edit
    reverted) and for projects without a `compile_incremental.sh`.
- **Unverified**: ccache is installed neither here nor on gh1. Before enabling it by default, test cache hits
  across two copies at different paths (`CCACHE_BASEDIR`), and that the wrapper survives CMake's compiler
  detection, autotools `configure` and plain Makefiles.

### 5.5 `compile_incremental.sh` (decision 2)
- Optional, resolved like `compile.sh`: `<configuration>/compile_incremental.sh`, then the shared one. A
  validation counterpart `compile_validate_incremental.sh` resolves the same way, else the validation build is full.
- Contract (docs + GUI help text):
  - It runs in a slot that was **already built** by `compile.sh` with the same environment, after the changed
    sources were written with a fresh mtime. Same variables as `compile.sh`, plus `DP_BUILD_KIND=incremental`
    (`compile.sh` gets `DP_BUILD_KIND=full`).
  - It must only rebuild: no `rm -rf`, no `make clean`, normally no configure.
  - It must build the target that `execute.sh` runs, through the build system's dependency tracking. For a
    superbuild, build the inner project directly or mark it `BUILD_ALWAYS`; for Makefiles, make sure header
    dependencies are tracked (`-MMD -MP`).
  - Exit code ≠ 0 → the project manager falls back to a reset + `compile.sh` (one retry, logged).
  - Examples in the docs for CMake (`cmake --build build`), a CMake superbuild (Kripke: `cmake --build
    build/kripke-build`), plain make, autotools (`make`), meson (`ninja -C build`).
- The GUI's configuration assistant offers to create it from the detected build system: if `compile.sh`
  contains `cmake --build <dir>` / `make` / `ninja`, propose that line alone. Always as a proposal the user
  confirms, never silently.
- **Generic stale-binary guard** (hazard 4, any build system): snapshot the mtimes of the slot's files outside
  the synced sources before the incremental build. If sources were changed by the sync and the build wrote
  **no** file, warn ("the incremental build rebuilt nothing although N sources changed: the binary is probably
  stale, check `compile_incremental.sh`"), and treat it as failed → reset + full build (decision 8). This catches the
  Kripke superbuild case without knowing anything about CMake. Checked: after a source change, Kripke's outer
  `cmake --build build` exits 0 and writes **0 files** below `build/`. It cannot catch a build that rebuilds
  *something* but not everything (missing header dependencies). That remains the verify mode's job.
- Verify mode for tests and for users who want certainty (`--verify-incremental`, also in the GUI): after the
  incremental build, build the same content state from scratch in a temporary slot and compare the program's
  output (`execute.sh` + `validate.sh`), optionally the hashes of the files both builds produced. Expensive,
  never on by default.
- The "incremental" kind is recorded in the manifest and in `execution_results.json` entries (`build_kind`), so a
  suspicious measurement can be traced back.

### 5.6 Avoiding copies altogether (decision 4, "if possible")
- **`par` and every build with suggestions**: a copy is unavoidable (patched sources must not touch the user's
  tree). With slots, the copy is made **once per slot**, and
  later builds only sync the changed files. In disk and time, that is close to no copy.
- **`seq`, `dp`, `hd` without suggestions**: the sources are not modified, so the build could run on the
  project's own sources with an out-of-source build directory. This is only possible if the script builds
  out-of-source into a directory the project manager chooses. Opt-in via a new variable `$DP_BUILD_DIR`
  (a per-mode directory below `<project>_discopop_builds`), with the setting "build from the project's sources"
  available only when `compile.sh` uses it. Limits:
  - the user editing the sources during a build;
  - generated files written into the source tree (in-source builds, Makefile projects, autotools in-source)
    → not general, hence opt-in;
  - for `dp`, `DP_PROJECT_ROOT_DIR` / `FileMapping.txt` would hold the project's own paths. That simplifies
    `activate_run` (no path rewriting), but it is a second code path to test;
  - `execute.sh` runs in the tree today (`./build/prog`). Without a tree it would have to find the binary via
    `$DP_BUILD_DIR`, so both scripts change;
  - for `dp`, the build directory lies outside `DP_PROJECT_ROOT_DIR`, so sources generated into it count as
    outside the project and are no longer instrumented (unlike in a slot).

  What it would save beyond slots is small, because the build directory dominates the disk usage, not the
  source copy: relearn's sources are 43 MB against a 695 MB build directory. Kripke's checkout is 199 MB plus
  347 MB of `.git`, which copies include today, against a 25 MB build. The cheaper win is to leave out `.git`
  and large data from slot copies (`copy_exclude`, §5.3). Keep `.git` where a build reads version info from
  it, so the default should be "keep, configurable".

  **Decided 2026-11-24: not pursued.** No `$DP_BUILD_DIR`; `compile.sh` stays unchanged.
- `--inplace` stays as it is.

### 5.7 Concurrency and the autotuner
- The evolutionary search compiles one candidate after the other, like every other strategy (decision 7). The
  `Pool` in `__compile_population` (`optimization/evolutionary_combination.py:799`) becomes a plain loop over the
  population, ordered so that consecutive candidates differ little: greedy nearest neighbour by symmetric
  difference of the suggestion sets, starting from the slot's current set. That keeps the files to resync
  per step small. There is one `par` slot per owner. The progress bar and the fitness cache stay.
- Runs happen in the tree (`running.py execute_in_build`), so the slot lock covers build **and** run of a
  candidate. A slot must not be resynced while its binary runs.
- `CodeConfiguration` moves onto the build API: `create_copy` + `apply_suggestions` + `compile_only` become one
  `ensure_build(BuildKey(owner, "par"), suggestions=…)` that returns a locked slot. `deleteFolder` becomes
  "release slot". The `PatchApplicationResult` per candidate stays (the refusal to measure unpatched code). The
  reference configuration is built in the `par` slot with the empty set, no longer in the user's project
  (removes the source of hazard 2).
- The autotuner flag `--skip-cleanup` keeps its meaning for the remaining temporary copies (e.g. a verify build).

### 5.8 Configuration and restriction (decision 5)
Project setting `.discopop/project/build_trees.json`, CLI on project manager and autotuner, GUI *Build* stage
(section "Build trees", Advanced):
- `modes`: which modes keep a persistent tree (default: all four). A mode that is left out builds in a temporary
  copy that is deleted after its run (today's behaviour for the autotuner).
- `validation_trees`: separate trees for validation builds (default on; off = the validation build runs in
  the mode's tree and marks it `dirty` → next build is a reset).
- `max_disk`: optional cap. When it is exceeded, the least recently used slot is deleted before a new one is
  filled. This is the only automatic deletion, and it is configured by the user.
- CLI: `--build-tree-modes seq,par`, `--no-validation-trees`, `--max-build-disk 20G`.
- The *Build* stage table lists slots with mode, role, content state (suggestions, last sync), last build kind
  (full / incremental), size, and a delete action. The existing `--delete-builds` handles slots.

### 5.9 Migration
- Existing per-suggestion-set builds (`<config>_par_s<hash>`) stay readable and deletable. New builds use slots.
  `list_builds` shows both. No automatic deletion of the old ones; a one-time note in the console names
  their size.
- `activate_run` / runs (`<build id>.runs/<run id>`) keep working: a run records the content state of the
  slot it ran in. A slot resync makes earlier runs of that slot "of an older build state". This is the same
  rule as for a rebuilt tree today, and `activate_run` refuses runs of builds with suggestions anyway.

## 6. Phased plan
Each phase is a pull request of its own, with tests, mypy, black and ruff, and docs
(`docs/tools/Project_manager.md` sections "Builds" / "Compile script resolution", `docs/tools/Autotuner.md`).

1. **Copies leave out configured build directories** (§5.3). Small and independent; fixes hazard 2 today.
   Tests: copy of a tree with a `CMakeCache.txt` dir, an autotools out-of-source dir, an in-source autotools
   project (must keep its `Makefile`).
2. **Fingerprint split + slots with content sync, full builds only** (§5.1, §5.2, §5.8 basics). One tree per
   mode/role, `compile.sh` in the synced slot. Saves the copy and disk; correct by construction (full
   script). Tests: sync unit tests (mtime trap, deletions, A→B→A, interrupted sync → reset), every fingerprint
   part classified, e2e build of a two-config project.
3. **`compile_incremental.sh`** (§5.5) for `seq`/`par`: resolution, `DP_BUILD_KIND`, fallback, stale-binary
   guard, `build_kind` in results, GUI help + assistant proposal, docs with the examples. Tests: e2e with a CMake
   multi-TU program and ≥ 3 suggestions in different files (sequence of sets; recompiled TU count; output
   equal to a from-scratch build); a superbuild-like case (ExternalProject without `BUILD_ALWAYS`) must be
   caught by the guard; a failing incremental script recovers via the full build.
4. **Autotuner on slots** (§5.7): `CodeConfiguration` on the build API, reference build in the slot, the
   evolutionary search compiles sequentially in nearest-neighbour order. Tests: existing autotuner tests,
   order of the evolutionary compile loop.
5. **Incremental `dp` / `hd`**, only after a test shows that instrumented partial rebuilds produce the same
   profiling data as full ones (compare `FileMapping.txt`, static data, the dependencies of a run).

Final check of phases 3-4 on gh1: relearn autotuner search (`par`, clang-22) with and without
`compile_incremental.sh` (`cmake --build "$DP_PROJECT_ROOT_DIR/dp_build" --target relearn -j …`). Also Kripke
locally with the inner-build incremental script, plus LULESH and miniFE (expected: no gain, no harm).

## 7. Risks
- **Stale binaries → fabricated measurements**, the same failure class the patch applicator guards against.
  Mitigations: content sync with fresh mtimes, the generic "rebuilt nothing" guard, the fallback to a full
  build, `build_kind` recorded, verify mode, and opt-in via a script the user writes.
- **Header patches** (relearn: 25 of 71 suggestions) may recompile many TUs. Incremental is then only a little
  faster, but never slower than a full build plus configure.
- **Disk**: one tree per mode and role (relearn: about 0.7 GB build + sources each). Bounded by §5.8, and less than today's one tree per suggestion set.
- **Scripts that build outside the tree** (`$DP_PROJECT_ORIGINAL_DIR`, fixed absolute paths): no per-slot
  state; already racy today. Documented as unsupported for incremental builds.

## 8. Open questions
1. ~~ccache~~: deferred (decision 3).
2. ~~stale-binary guard~~: falls back to a full build (decision 8).
3. ~~building without copies (`$DP_BUILD_DIR`)~~: not pursued (§5.6).
