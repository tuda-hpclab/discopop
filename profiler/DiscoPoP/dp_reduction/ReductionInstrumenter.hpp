/*
 * This file is part of the DiscoPoP software
 * (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */

#pragma once

#include <cstdint>
#include <fstream>
#include <functional>
#include <string>
#include <vector>

#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instruction.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"

#include "Structs.hpp"
#include "utils/profiler_files.hpp"

namespace dp_reduction {

// What the reduction pass takes from the rest of the pass: it has to number its loops the way the control flow
// analysis does, name variables as the pass does and know the file ids of the functions.
struct Services {
  std::function<int32_t(llvm::Function&)> get_file_id;
  std::function<int32_t(llvm::Loop*)> get_loop_id;
  std::function<std::string(llvm::Instruction*)> get_variable_name;
};

// The reduction pass for one module: finds the loops and the instructions that may be part of a reduction
// (instrument_module), writes them to reduction.txt and loop_meta.txt and inserts the calls that count the
// iterations of the loops (insert_functions). Owns the files and the findings of the module.
class ReductionInstrumenter {
 public:
  ReductionInstrumenter(llvm::Module& module, Services services);

  // iterates over all functions in the module and calls 'instrument_function' on suitable ones
  void InstrumentModule(llvm::ModuleAnalysisManager& mam);

  // inserts calls to allow for dynamic analysis of the loops
  void InsertFunctions();

  // closes (and so flushes) the files
  void Close();

 private:
  // iterates over all loops in a function and calls 'instrument_loop' for each one
  void InstrumentFunction(llvm::Function* function, llvm::LoopInfo& loop_info);

  // determines which instructions of a loop might be suitable for a reduction; adds an entry to 'loops_' and
  // one to 'instructions_' for each suitable instruction
  void InstrumentLoop(llvm::Function& f, int file_id, llvm::Loop* loop, llvm::LoopInfo& li);

  llvm::Module& module_;
  Services services_;
  profiler_files::FileLock reduction_file_lock_;
  std::ofstream reduction_file_;
  std::vector<LoopInfoT> loops_;
  std::vector<InstrInfoT> instructions_;
};

}  // namespace dp_reduction
