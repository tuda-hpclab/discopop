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

#include <map>
#include <memory>
#include <string>

#include "llvm/IR/DerivedTypes.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"

#include "DPUtils.hpp"

namespace hybrid_analysis {

// The hybrid analysis (instrumentation omission) of a module: predicts the dependencies of the
// accesses to local variables statically, reports them per execution of their basic blocks
// instead of profiling them, and erases the callbacks of these accesses. Owns the dependency
// string handed to the runtime and the static memory region ids.
class HybridAnalysis {
 public:
  // declares __dp_report_bb, __dp_report_bb_pair and __dp_bb_state and reads the counters
  // persisted by the modules compiled before
  explicit HybridAnalysis(llvm::Module& m);

  // Runs after F was instrumented (see DiscoPoP::runOnFunction): needs the instruction ids and
  // the inserted access callbacks, and erases those of the omitted accesses.
  // trueVarNamesFromMetadataMap is not const on purpose: looking up a local without a debug
  // record adds an empty name for it, which the later functions of the module then use.
  bool AnalyzeFunction(llvm::Function& f, llvm::ModuleAnalysisManager& mam,
                       std::map<llvm::Instruction*, llvm::CallInst*>& inserted_access_callbacks,
                       std::map<std::string, std::string>& true_var_names_from_metadata_map);

  // hands the dependencies of the module over to the runtime and persists the counters
  void Finalize(llvm::Module& m);

 private:
  llvm::IntegerType* int32_;
  llvm::FunctionCallee report_bb_, report_bb_pair_, bb_state_;
  std::unique_ptr<dputil::VariableNameFinder> vnf_;
  std::string bb_dep_string_;
  // only used by the disabled dot output of the CFG and DG
  std::string file_name_;
};

}  // namespace hybrid_analysis
