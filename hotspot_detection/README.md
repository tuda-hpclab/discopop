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

# Hotspot-Detection

Hotspot-Detection is an open-source tool that helps software developers to detect hotspots in their programs. This allows to focus optimization efforts to where it really matters.

Code regions (loops and functions) are categorized into three classes (HOT, WARM, COLD) according to the following criteria:

A) the code region contributes a lot to the total runtime of the program. \
B) the runtime of the code region increases a lot when using different program parameters.

- HOT code regions fulfill both _(A and B)_
- WARM code regions fulfill only one _(A xor B)_
- COLD code regions fulfill neither  _(not(A or B))_


## Installation

Hotspot-Detection is part of the [DiscoPoP](https://github.com/tuda-hpclab/discopop) framework.

### Install as part of DiscoPoP
```
pip install discopop
```

### Install standalone
```
pip install discopop-hotspot-detection
```

### Prerequisites for building from source
- LLVM/clang version 19, 20, 21, or 22 (installed and on `PATH`)

## Usage

The Hotspot-Detection has two core components:
- The **LLVM pass** instruments your program during compilation to measure the time spent in each code region.
- The **`discopop_hotspot_analyzer`** Python tool analyzes the measured runtimes and reports hotspots.

### 1) Build your project with hotspot-detection instrumentation

**For individual source files**, use the provided compiler wrappers directly:
```
discopop_hotspot_cc  source.c   -o program   # C files
discopop_hotspot_cxx source.cpp -o program   # C++ files
```

**For CMake-based projects**, pass the wrappers as the C/CXX compiler.
The `-DCMAKE_*_COMPILER_WORKS=1` flags skip CMake's compiler detection, which is necessary because the wrappers add instrumentation flags that CMake's test programs do not expect.
```
cd <your_project_directory>
mkdir build && cd build
cmake -DCMAKE_C_COMPILER_WORKS=1 \
      -DCMAKE_CXX_COMPILER_WORKS=1 \
      -DCMAKE_C_COMPILER=discopop_hotspot_cc \
      -DCMAKE_CXX_COMPILER=discopop_hotspot_cxx \
      ..
make
```

### 2) Run the instrumented program

Run your program multiple times with varying parameters.

```
./<your_program_name> <your_program_arguments_1>
./<your_program_name> <your_program_arguments_2>
./<your_program_name> <your_program_arguments_3>
# ...
```

### 3) Analyze the results

Change your working directory to the `.discopop` directory (created inside the build directory by default).

```
cd .discopop
discopop_hotspot_analyzer
```

You can now find the analysis results inside `.discopop/hotspot_detection`.

### 4) Convenience

For a more convenient management of the process and inspection of the results, please consider using our [Visual Studio Code Extension](https://marketplace.visualstudio.com/items?itemName=TUDarmstadt-LaboratoryforParallelProgramming.discopop).

### Publication

1. Seyed Ali Mohammadi, Lukas Rothenberger, Gustavo de Morais, Bertin Nico Görlich, Erik Lille, Hendrik Rüthers, and Felix Wolf. 2023. Filtering and Ranking of Code Regions for Parallelization via Hotspot Detection and OpenMP Overhead Analysis. In Proceedings of the SC '23 Workshops of The International Conference on High Performance Computing, Network, Storage, and Analysis (SC-W '23). Association for Computing Machinery, New York, NY, USA, 1368–1379. https://doi.org/10.1145/3624062.3624206

### Citation

Please cite in your publications if it helps your research:

	@inproceedings{10.1145/3624062.3624206,
		author = {Mohammadi, Seyed Ali and Rothenberger, Lukas and de Morais, Gustavo and G\"{o}rlich, Bertin Nico and Lille, Erik and R\"{u}thers, Hendrik and Wolf, Felix},
		title = {Filtering and Ranking of Code Regions for Parallelization via Hotspot Detection and OpenMP Overhead Analysis},
		year = {2023},
		isbn = {9798400707858},
		publisher = {Association for Computing Machinery},
		address = {New York, NY, USA},
		url = {https://doi.org/10.1145/3624062.3624206},
		doi = {10.1145/3624062.3624206},
		booktitle = {Proceedings of the SC '23 Workshops of The International Conference on High Performance Computing, Network, Storage, and Analysis},
		pages = {1368–1379},
		numpages = {12},
		keywords = {parallelization overhead, expected benefits, OpenMP microbenchmarks, Hotspot detection, ranking, performance analysis},
		location = {Denver, CO, USA},
		series = {SC-W '23}
	}
