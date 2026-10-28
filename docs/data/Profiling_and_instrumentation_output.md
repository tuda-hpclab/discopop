---
layout: default
title: Profiling and instrumentation output
parent: Data
nav_order: 1
---

# Profiling and instrumentation output

The compiler pass (`discopop_cc` / `discopop_cxx`, see [Compiler wrappers](../tools/Instrumentation.md)) and the runtime library of an instrumented program write their results to `.discopop/profiler/` (more precisely `$DOT_DISCOPOP/profiler`, see [Environment variables](../setup/environment_variables.md)). The [explorer](../tools/Explorer.md) reads them.

{: .important }
Every compiled module and every run appends to the files in `.discopop/profiler`; the wrappers never clean the directory. Remove `.discopop` before you instrument a project again, otherwise stale data from earlier builds remains. The ids of instructions, CUs and callpath states are handed from module to module via the `DP_*Counter.txt` files and are only unique within one build.

The examples on this page come from `example/example.cpp` of the repository (file ids and line numbers refer to it).

| File | Written by | Read by | Content |
|---|---|---|---|
| `Data.xml` | pass | explorer | computational units (CUs), functions, loops |
| `static_dependencies.txt` | pass | explorer | dependencies found by static analysis |
| `dynamic_dependencies.txt` | runtime | explorer | dependencies, loop and function control lines |
| `instructionID_to_lineID_mapping.txt` | pass | explorer | instruction id to source location |
| `loop_counter_output.txt` | runtime | explorer | total iterations per loop |
| `loop_meta.txt` | pass | runtime | loop id to file and line |
| `loopstate_positions.txt` | pass | explorer | meaning of the loop digits in callpath state labels |
| `stateID_to_callpath_mapping.txt` | pass | explorer | callpath state tree |
| `callpath_state_transitions.txt` | pass | runtime | state transitions per instruction |
| `callpath_state_return_targets.txt` | pass | runtime | states reached when a function returns |
| `callpath_function_entries.txt` | pass | runtime | entry states of functions |
| `initial_stateID.txt` | pass | runtime | state of `main` |
| `reduction.txt` | pass | explorer | reduction instructions |
| `DP_*Counter.txt` | pass | pass | id counters |
| `ast_dump.json` | compiler wrapper | explorer | filtered clang AST |
| `statistics/profiling_time.txt` | runtime | - | time of the profiling run |
| `OriginalVariables.txt` | pass | - | always empty, kept for compatibility |
| `*.dot` | pass | - | debugging output, only with `DP_WRITE_CALLPATH_DOT` |
| `cu_taken_branch_counter_output.txt` | runtime | optimizer | only with `DP_BRANCH_TRACKING` |

## Data.xml

`Data.xml` contains the computational units (CUs) of the project, its functions and its loops, as `<Node>` elements. Each node has an id (`<file id>:<node id>`, see [File mapping](Filemapping.md)), a type, a name (many nodes have an empty name) and the start and end line (`<file id>:<line>`):

```xml
<Node id="1:6" type="2" name="" startsAtLine = "1:20" endsAtLine = "1:22">
    <childrenNodes>1:7,1:8,1:9</childrenNodes>
</Node>
```

| Type | Node | Content |
|---|---|---|
| 0 | CU | the atoms of parallelization; DiscoPoP does not look inside a CU |
| 1 | function | children: CUs and loops of the function |
| 2 | loop | children: CUs and loops inside the loop |
| 3 | dummy | function without source code, for example a library function; it is not profiled and gets no suggestions |

Function nodes carry `funcArguments` (one `<arg type defLine accessMode>name</arg>` per argument) and `funcReturnLines` (the lines of the return statements, separated by `, `):

```xml
<Node id="0:0" type="1" name="main" startsAtLine = "1:15" endsAtLine = "1:27">
    <childrenNodes>1:1,1:2,1:3,1:4,1:5,1:6,1:10,1:11,1:15,1:16</childrenNodes>
    <funcArguments>
    </funcArguments>
    <funcReturnLines>1:27, </funcReturnLines>
</Node>
```

CU nodes follow a read-after-write pattern. They contain:

| Element | Content |
|---|---|
| `childrenNodes` | child nodes (empty for CUs) |
| `BasicBlockID` | name (label) of the LLVM basic block the CU lies in, for example `entry` or `for.cond`; a basic block may contain several CUs, a CU never spans several basic blocks |
| `readDataSize`, `writeDataSize` | bytes read and written in the CU, computed from the LLVM-IR load and store instructions |
| `performsFileIO` | `1` if the CU performs file I/O, else `0` |
| `instructionsCount` | number of LLVM-IR instructions |
| `instructionIDs` | ids of the instructions of the CU (attribute `count`: number of instructions); the ids are those of `instructionID_to_lineID_mapping.txt` and the dependencies |
| `jumpInstructionIDs` | the subset of these instructions that are jumps (the terminators of a basic block, e.g. `br`, `switch`, `ret`, `unreachable`; except `invoke` and `callbr`), attribute `count` as above. A jump carries the line of a closing brace or of the jump over an `else`, no statement; the explorer does not count a line that holds only jumps as part of a task |
| `instructionLines`, `readPhaseLines`, `writePhaseLines`, `returnInstructions` | source lines of all instructions, loads, stores and return instructions (attribute `count`: number of lines) |
| `successors` | `<CU>id</CU>` for each CU that can execute after this one |
| `localVariables` | variables that live within the CU: `<local type defLine accessMode>name</local>` |
| `globalVariables` | variables that break the read-after-write rule and thus start a new CU: `<global type defLine accessMode>name</global>` |
| `callsNode` | functions called by the CU: `<nodeCalled atLine callInstId>function node id</nodeCalled>`, each followed by a `<recursiveFunctionCall>` element that records whether the call is recursive |

The explorer needs `instructionIDs` (it stops with an error for a CU without them). `Data.xml` files written by an older profiler lack both elements and are not supported: reinstall the profiler (`pip install ./profiler`, not editable), remove `.discopop` and instrument and profile the program again. Without `jumpInstructionIDs` the explorer would not fail but also could not tell jump-only lines, which makes the lines of tasks less exact.

`accessMode` is `R`, `W` or `RW`; `defLine` is the line the variable is defined in, or `LineNotFound`.

```xml
<Node id="1:2" type="0" name="" startsAtLine = "1:16" endsAtLine = "1:17">
    <childrenNodes></childrenNodes>
    <BasicBlockID>entry</BasicBlockID>
    <readDataSize>32</readDataSize>
    <writeDataSize>128</writeDataSize>
    <performsFileIO>0</performsFileIO>
    <instructionsCount>2</instructionsCount>
    <instructionLines count="2">1:16,1:17</instructionLines>
    <instructionIDs count="2">25,26</instructionIDs>
    <jumpInstructionIDs count="0"></jumpInstructionIDs>
    <readPhaseLines count="0"></readPhaseLines>
    <writePhaseLines count="2">1:16,1:17</writePhaseLines>
    <returnInstructions count="0"></returnInstructions>
    <successors>
        <CU>1:3</CU>
    </successors>
    <localVariables>
    </localVariables>
    <globalVariables>
        <global type="ptr" defLine="1:16" accessMode="W">N</global>
        <global type="ptr" defLine="1:17" accessMode="W">sum</global>
    </globalVariables>
    <callsNode>
    </callsNode>
</Node>
```

## Dependencies

DiscoPoP combines the dependencies found by the runtime library (`dynamic_dependencies.txt`) with those the pass determines statically (`static_dependencies.txt`).

### dynamic_dependencies.txt

The profiler uses instruction ids instead of line numbers. Every instrumented instruction has an id; `instructionID_to_lineID_mapping.txt` maps it to a source location. A dependency line has the format

```text
<sink instruction id>@<sink state id> NOM  <TYPE> <source instruction id>@<source state id>|<variable>(<memory region>) [<TYPE> ...]
```

- `TYPE` is `RAW`, `WAR`, `WAW` or `INIT` (the first write to a memory address; its source is `0@0` or `*`)
- the state ids are [callpath states](#callpath-states); they separate the dependencies of different call paths and loop iterations
- `NOM` is a constant token; several dependencies of one sink are written on the same line, separated by spaces
- `memory region` is the id of the accessed memory region, or `S<n>` for a static memory region assigned by the pass

The file also contains control lines that describe loops and functions:

```text
START 1:15
1:24 BGN loop 100000 1 100000 100000
1:27 END loop
1:20 BGN loop 100000 1 100000 100000
1:24 END loop
* BGN func 1:15
1:27 END func
49@26 NOM  INIT 0@0|GEPRESULT_vla(97768979329069)
63@25 NOM  RAW 74@24|i(S7)
46@22 NOM  RAW 53@27|i(S6)
53@27 NOM  WAR 51@27|i(S6)
36@13 NOM  INIT *|__vla_expr0(S5)
```

| Line | Meaning |
|---|---|
| `START <file id>:<line>` | start of the program (here the start line of `main`) |
| `<line> BGN loop <total iterations> <entries> <average iterations> <maximum iterations>` | begin of a loop control region, with the iteration counts of the whole run; `<line>` is `<file id>:<line>` |
| `<line> END loop` | end of a loop control region |
| `<call site or *> BGN func <function start line>` | begin of a function region |
| `<line> END func` | end of a function region |
| `* END program` | last line of the file |

### static_dependencies.txt

The pass writes the dependencies it can determine without running the program, in the format `<instruction id> NOM <TYPE> <instruction id>|<variable>(S<n>)`. The explorer merges both files.

```text
25 NOM INIT *|N(S1)
27 NOM RAW 25|N(S1)
53 NOM WAR 51|i(S6)
```

### instructionID_to_lineID_mapping.txt

One line per instruction id: `<instruction id> <file id>:<line>:<column>`, or `*` if the instruction has no source location.

```text
2 *
3 1:15:0
25 1:16:7
```

## Loops

The profiling run counts the iterations of every loop.

`loop_counter_output.txt` has one line per loop with the total number of executed iterations, in the format `<file id> <line> <total iterations>`:

```text
1 20 100000
1 24 100000
```

`loop_meta.txt` is written by the pass and read by the runtime. It has one line per loop, in the format `<file id> <loop id> <line>`; the loop id is local to a module:

```text
1 1 24
1 0 20
```

`loopstate_positions.txt`: the loops of a function are part of its callpath states (see below). The state labels have the form `<function>_loopstate<digits>` with one digit per loop of the function: `0`, `1` or `2` name the iteration bucket of an active loop, `3` marks an inactive loop. The file tells which loop each digit stands for. Each line describes one digit position of one function, in the format `<function name> <position> <loop id> <loop node id> <file id>:<start line>`:

```text
main 0 0 1:6 1:20
main 1 1 1:11 1:24
```

`position` is the index of the digit (from 0), `loop id` the id used in `loop_meta.txt`, `loop node id` the node id of the loop in `Data.xml`, and the last column its start line; both are `-` if unknown. The positions follow a pre-order traversal of the loop nesting of the function. Loops that are not instrumented for loop entry and exit are not listed. A function that is compiled in several modules (for example an inline function of a header) is listed once per module.

## Callpath states

The profiler distinguishes dependencies by the call path and the loop iterations in which they occur. The pass enumerates the possible call paths of the program and gives each one a state id. The runtime library follows the state transitions while the program runs and reports the current state with every access (the `@<state id>` in the dependency lines).

`stateID_to_callpath_mapping.txt` holds the tree of states, one line per state: `<state id> <parent state id> <label>`. The root state `ROOT` is its own parent. The labels are function names, `<function>_loopstate<digits>` for a function with active loops (see `loopstate_positions.txt`), and the names of the runtime callbacks the pass inserts (`__dp_*`).

```text
1 1 ROOT
13 1 main
22 13 main_loopstate03
23 13 main_loopstate30
24 23 main_loopstate31
```

`callpath_state_transitions.txt`: the first line is a comment starting with `#`, which readers skip. Every other line has the format `<source state id> <instruction id> <target state id>`: when the instruction executes in the source state, the program moves to the target state (a call, a loop entry or a loop increment).

```text
# Format: <source_state_id> <instruction_id> <target_state_id>
13 39 22
13 58 23
22 81 26
```

`callpath_state_return_targets.txt`: the format is `<source state id> <target state id>` (the first line is a comment). It lists the states that are reached when a function returns. A program that consists only of `main` has no entries.

`callpath_function_entries.txt`: the runtime follows a call into a function's callpath state only if the call enters an instrumented function and the transition leads to a state of that function. Otherwise (a call from another module, an indirect or virtual call, a call by library code) it continues in the root state of the entered function, if one exists; if none exists, the caller's state is kept until the function is left. Leaving a function always restores the caller's state. The file identifies a function by the instruction id of its entry instrumentation. `S <state id> <function entry id>` marks a state as entry state of an instance of the function, `E <function entry id> <state id>` names its root entry state. The first line is a comment.

```text
# Format: S <state_id> <function_entry_instruction_id> | E <function_entry_instruction_id> <root_state_id>
S 13 2
E 2 13
```

`initial_stateID.txt` contains the state id of `main`, the state the program starts in (`13` in the example).

## Reduction instructions

`reduction.txt` lists the reduction instructions the pass found, one per line:

```text
 FileID : 1 Loop Line Number : 24 Reduction Line Number : 25 Variable Name : sum Operation Name : +
```

`FileID` is the id of the file (see [File mapping](Filemapping.md)), `Loop Line Number` the line of the loop that contains the reduction, `Reduction Line Number` the line of the operation, and `Operation Name` the operation. The pass reports `+`, `-`, `*`, `&`, `|` and `^`, and `>` for a conditional update (the maximum or minimum pattern, which the explorer calls `max`). See [Reduction](Parallel_patterns/reduction.md).

## Other files

- `DP_InstructionIDCounter.txt`, `DP_CUIDCounter.txt`, `DP_CallpathStateIDCounter.txt`, `DP_BBDepCounter.txt`, `DP_StaticMemoryRegionIDCounter.txt`: the next free id of each kind (a plain number). Each compiled module reads them and writes them back, so ids are unique across the modules of a build.
- `ast_dump.json`: the clang AST of the compiled files, reduced to what the explorer needs. The compiler wrappers append it for every compilation; the AST utilities of the explorer read it.
- `statistics/profiling_time.txt`: the time the profiling run took, for example `23 ms`.
- `OriginalVariables.txt`: always empty, kept for compatibility.
- `callpath_state_transitions.dot`, `static_calltree.dot`: graphs for debugging, written only if the environment variable `DP_WRITE_CALLPATH_DOT` is set when you compile (they become very large for large programs). Nothing reads them.
- `cu_taken_branch_counter_output.txt`: written only if the runtime library was built with `DP_BRANCH_TRACKING`; one line `<cu id>;<count>` per CU. The optimizer reads it.

## Runtime settings

The runtime library reads optional settings from a file `dp.conf` next to the instrumented executable. They are described in [Environment variables and runtime settings](../setup/environment_variables.md#runtime-settings-dpconf).
