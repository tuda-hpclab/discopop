---
layout: default
title: Home
nav_order: 1
---

# DiscoPoP - Discovery of Potential Parallelism
DiscoPoP is an open-source tool that helps software developers parallelize their programs with threads. It is a joint project of the [Laboratory for Parallel Programming @ TU Darmstadt](https://github.com/tuda-parallel) and the Iowa State University.

In a nutshell, DiscoPoP performs the following steps:
* detect parts of the code (computational units or CUs) with little to no internal parallelization potential,
* find data dependences among them,
* identify parallel patterns that can be used to parallelize a code region,
* and finally suggest corresponding OpenMP parallelization constructs and clauses to programmers.

DiscoPoP is built on top of LLVM. Therefore, DiscoPoP can perform the above-mentioned steps on any source code which can be transferred into the LLVM IR.

A more comprehensive overview of DiscoPoP can be found on our [project website](https://www.discopop.tu-darmstadt.de/).

## Getting started
Follow the steps in [setup](setup/discopop.md) to install DiscoPoP.
To setup the [Visual Studio Code Extension](https://marketplace.visualstudio.com/items?itemName=TUDarmstadt-LaboratoryforParallelProgramming.discopop) (recommended for general use of the framework), please follow [these steps](setup/vscx.md).

For a brief introduction into the [VSCode Extension](https://marketplace.visualstudio.com/items?itemName=TUDarmstadt-LaboratoryforParallelProgramming.discopop), please follow the [walk-through example](examples/walk_through_gui.md).
For a brief introduction into the command line tools, please refer to the [tools overview](tools/tools.md) and follow the [command-line walk-through example](examples/walk_through.md).

For detailed information on the gathered and stored data as well as the tools themselves, please refer to [data](data/data.md) and the pages of the individual tools in the [tools overview](tools/tools.md).

## TL;DR
This example installs DiscoPoP, instruments and builds the provided example, analyzes the results and prints the identified parallelization suggestions to the console.
In case any issues arise during the process, please refer to the detailed [setup instructions](setup/setup.md), contact us via GitHub messages, or get in contact by mail to [discopop-support@lists.parallel.informatik.tu-darmstadt.de](mailto:discopop-support@lists.parallel.informatik.tu-darmstadt.de).
```
# setup DiscoPoP
git clone git@github.com:tuda-hpclab/discopop.git
cd discopop
mkdir build && cd build
DP_BUILD=$(pwd)
cmake .. && make
# instrument and build the example code
cd ../example
mkdir build && cd build && cmake -DCMAKE_CXX_COMPILER=${DP_BUILD}/scripts/CXX_wrapper.sh .. && make
# execute instrumented code
./cmake_example
# identify parallel patterns
cd .discopop
discopop_explorer
# create applicable patches from patterns
discopop_patch_generator
# print patches to the console
for f in $(find patch_generator -maxdepth 1 -type d); do
    echo "SUGGESTION: $f"
    cat $f/1.patch
    echo ""
done
# apply patch with id 1
discopop_patch_applicator -a 1
# reset code to the original state
discopop_patch_applicator -C
```


## Exemplary output
The following is an automatically generated, exemplary output patch file generated and applicable as show in the provided [examples](examples/examples.md).
```
 --- /home/lukas/temp/discopop_tmp/discopop/example/example.cpp	2024-01-09 10:11:50.369555235 +0100
+++ /home/lukas/temp/discopop_tmp/discopop/example/example.cpp.discopop_patch_generator.temp	2024-01-09 11:14:20.904823624 +0100
@@ -20,6 +20,7 @@
         Arr[i] = i % 13;
     }

+    #pragma omp parallel for shared(Arr,N) reduction(+:sum)
     for(int i = 0; i < N; i++){
         sum += Arr[i];
     }
```

## License
© DiscoPoP is available under the terms of the BSD-3-Clause license, as specified in the LICENSE file.
