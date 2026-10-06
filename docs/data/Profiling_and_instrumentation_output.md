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

DiscoPoP uses a signature to store data dependences. You can configure the settings of this signature, and of the profiler's worker threads, by creating a `dp.conf` file in the directory that contains the instrumented executable. Each line has the form `<PARAMETER>=<positive integer>`; the following parameters are supported:

- `SIG_ELEM_BIT`: Size of each element in the signature in bits.
- `SIG_NUM_ELEM`: Size of the signature. The bigger it is, the less false positives/negatives are reported.
- `SIG_NUM_HASH`: Number of signatures. A value of two indicates that one signature is used for read accesses and one signature for write accesses.
- `USE_PERFECT`: When it is set to one, DiscoPoP uses a perfect signature. The default value is one.
- `NUM_WORKERS`: Number of worker threads that analyze the recorded memory accesses. Overrides the value set at build time via `-DDP_NUM_WORKERS`.
- `FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER`: Number of recorded chunks of memory accesses (100000 accesses, about 4 MB each) that may wait for a worker thread, per worker. When the limit is reached, the profiled program waits for the workers. Default: 4.
- `SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER`: Number of analyzed chunks (up to about 11 MB each) that may wait to be merged into the global results, per worker. The merging is done by a single thread; when the limit is reached, the workers wait for it. Larger values cost memory without speeding up the profiling. Default: 4.

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
