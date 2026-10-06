---
layout: default
title: Profiling and instrumentation output
parent: Data
nav_order: 1
---

## Computational Units (CUs)

When you apply the `DiscoPoP` instrumentation pass, a file named `Data.xml` will be created.
It contains the identified computational units of the specified target project.

The xml file contains much information about the program. There are four types of nodes in the xml file including: functions, loops, CUs, and dummies. Each node has an ID (consisting of `file_id:cu_id`), a type, a name (some nodes have empty names) and the start and end line of the node in the source code.

Function nodes which are represented by type 1 contain information about functions in each file of the source code. Function nodes contain children nodes which can be CUs, loop nodes, and dummies. Also, you can find the list of function arguments there.

Nodes with type 0 are CUs. They follow a read-after-write pattern. They are the atoms of parallelization; meaning that we do not look inside a CU for parallelization opportunities. The information that we report for CUs are the following:

- `BasicBlockID`: The ID of the basic block that the CU happens in. A basic block is a block of code with single entry and exit points. A basic block may contain multiple CUs but a CU may not span over multiple basic blocks.
- `readDataSize`: number of bytes which is read in this CU. We consider LLVM-IR load instructions to compute this value.
- `writeDataSize`: Number of bytes written in this CU. It is computed like `readDataSize`.
- `instructionsCount`: Number of LLVM-IR instructions in the CU.
- `instructionLines`: The line numbers in which the CU appears.
- `readPhaseLines`: LLVM-IR load instructions which happen within the CU boundaries.
- `writePhaseLines`: LLVM-IR store instructions in the CU.
- `returnInstructions`: It indicates the line number of return instructions if the CU contains return instructions.
- `Successors`: The succeeding CU when analyzing the source code top-down in the source code.
- `localVariables`: the variables which appear within the CU. We also report the line number where the variable is defined, its name and its type.
- `globalVariables`: variables which break the read-after-write rule for the CU. They cause the creation of a new CU which will succeed the CU.
- `callsNode`: It indicates the line number of a called function if the CU contains a call instruction.

Loop nodes have type 2. They contain children nodes which can be CUs, other loops, or dummy nodes.

Dummy nodes are usually library functions whose source code is not available. We cannot profile them and thus do not provide parallelization suggestions for them.

Please note that DiscoPoP appends CUs to an existing `Data.xml` file and thus if you need to extract computational units of the program again, you need to remove the existing `Data.xml` file.

## Data Dependencies

DiscoPoP uses a signature to store data dependences. You can configure the settings of this signature by creating a dp.conf file in the root directory of your program. The contents of the config file usually contains the following parameters:

- `SIG_ELEM_BIT`: Size of each element in the signature in bits.
- `SIG_NUM_ELEM`: Size of the signature. The bigger it is, the less false positives/negatives are reported.
- `SIG_NUM_HASH`: Number of signatures. A value of two indicates that one signature is used for read accesses and one signature for write accesses.
- `USE_PERFECT`: When it is set to one, DiscoPoP uses a perfect signature. The default value is one.

To find parallelization opportunities, we need to extract data dependencies inside the program. For that, we need to instrument the memory accesses, link the program with DiscoPoP run-time libraries, and finally execute the program with several representative inputs. The necessary steps are described [here](../Tutorials/Tutorials.md).
After executing the instrumented program, you find a text file which ends with `_dep.txt` which contains the data dependences identified using the provided input.
A data dependence is represented as a triple `<sink, type, source>`. `type` denotes the dependence type and can be any of `RAW`, `WAR` or `WAW`. Note that a special type `INIT` represents the first write operation to a memory address. `source` and `sink` are the source code locations of the former and the latter memory access, respectively. `sink` is further represented as a pair `<fileID:lineID>`, while source is represented as a triple `<fileID:lineID|variableName>`. The keyword `NOM` (short for "NORMAL") indicates that the source line specified by aggregated `sink` has no control-flow information. Otherwise, `BGN` and `END` represent the entry and exit points of a control region.

## Loop Counters
As part of the DiscoPoP profiling loops are instrumented with the purpose to count the total amount of executed iterations per loop as well as the average iteration count per loop entry.

### Total Loop Counters
The total observed iteration counts per loop will be stored in a file named `loop_counter_output.txt`.
Each line of the file contains the summed count of iterations for the specified loop.
The used format is as follows: `<file_id> <line_number> <total_iteration_count>`.

### Total Counters, Amount of Loop Entries, Averages and Maxima
The total, summed iteration counters per loops as well as the amount of loop entries, average iteration count per loop and the maximum observed iterations per single loop entry can be found in the previously described dependency file, which stores all information gathered during the profiling.
The used format is as follows: `<fileID>:<LineID> BGN loop <total_iteration_count> <loop_entry_count> <average_iteration_count> <maximum_iteration_count>`.

## Reduction Instructions
Identified reduction instructions are stored in a file named `reduction.txt`.
Each line of the file describes one identified reduction instruction in the code.
The format is quite simple and will be explained using the following example:

    FileID : 1 Loop Line Number : 10 Reduction Line Number : 12 Variable Name : sum Operation Name : +

`FileID` specifies the id of the file, as stored in `FileMapping.txt`, which contains the identified reduction operation.
`Loop Line Number` refers to the source code line of the loop which contains the identified operation.
`Reduction Line Number` refers to the source code line where the operation is located.
The name of the affected reduction variable is presented by `Variable Name` and `Operation Name` shows which operation is used for the reduction.

## Loopstate Positions
The callpath states written to `stateID_to_callpath_mapping.txt` describe the loops active within a function by labels of the form `<function>_loopstate<digits>`, carrying one digit per loop of the function: `0`, `1` or `2` name the iteration bucket of an active loop, `3` marks an inactive loop.
Which loop each digit position stands for is stored in a file named `loopstate_positions.txt`.
Each line of the file describes one digit position of one function.
The used format is as follows: `<function_name> <position> <loop_id> <loop_node_id> <file_id>:<start_line>`.

`function_name` is the (mangled) name used in the `_loopstate` labels, `position` the index of the digit within `<digits>`, counted from 0.
`loop_id` is the loop's id within its module, as used in `loop_meta.txt`.
`loop_node_id` is the id of the loop's node in `Data.xml`, and `<file_id>:<start_line>` the loop's start location, equal to that node's `startsAtLine`. Both are `-` if they are unknown.
The positions follow a pre-order traversal of the function's loop nesting forest.
Loops which are not instrumented for loop entry and exit, and thus are not part of the callpath states, are not listed.
Since every compiled module appends to the file, a function compiled in multiple modules (e.g. an inline function defined in a header) is listed once per module.
The loop nesting forest is taken from LLVM's loop analysis: the parent of a loop is its closest enclosing instrumented loop, and siblings keep the order of their loop entries in the code.

## Callpath Function Entries
The runtime library follows a call into a function's callpath state only when the call enters an instrumented function, i.e. on the callee's function entry, and only if the call's transition leads to a state of that function.
Otherwise (a call from another module, an indirect or virtual call, a call by library code) it continues in the root callpath state of the entered function, i.e. the state of the function without a caller in its module, if one exists; the callpaths of such states start with the entered function instead of `main`.
If neither exists, the caller's state is kept, without transitions, until the function is left. Leaving a function always restores the caller's state.
The required information is stored in a file named `callpath_function_entries.txt`, which identifies a function by the instruction id of its function entry instrumentation.
The used format is as follows: `S <state_id> <function_entry_id>` marks a state as the entry state of an instance of the function, and `E <function_entry_id> <state_id>` names the root entry state of the function.
