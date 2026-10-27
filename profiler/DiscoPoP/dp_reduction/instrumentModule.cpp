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

#include <string.h>

#include <string>
#include <utility>

#include "dp_reduction/ReductionInstrumenter.hpp"
#include "dp_reduction/dp_reduction.hpp"
#include "utils/profiler_files.hpp"

dp_reduction::ReductionInstrumenter::ReductionInstrumenter(llvm::Module& module, Services services)
    : module_(module), services_(std::move(services)), reduction_file_(profiler_files::Open("reduction.txt")) {}

void dp_reduction::ReductionInstrumenter::Close() {
  // closing flushes
  reduction_file_.close();
}

// iterates over all functions in the module and calls 'instrument_function'
// on suitable ones
void dp_reduction::ReductionInstrumenter::InstrumentModule(llvm::ModuleAnalysisManager& mam) {
  llvm::Module* module = &module_;
  for (llvm::Module::iterator func_it = module->begin(); func_it != module->end(); ++func_it) {
    llvm::Function* func = &(*func_it);
    const std::string fn_name = func->getName().str();
    if (func->isDeclaration() || (std::strcmp(fn_name.c_str(), "NULL") == 0) ||
        fn_name.find("llvm") != std::string::npos || dp_reduction::InlinedFunction(func)) {
      continue;
    }

    llvm::FunctionAnalysisManager& fam = mam.getResult<llvm::FunctionAnalysisManagerModuleProxy>(*module).getManager();
    llvm::LoopInfo& loop_info = fam.getResult<llvm::LoopAnalysis>(*func);

    InstrumentFunction(func, loop_info);
  }
}
