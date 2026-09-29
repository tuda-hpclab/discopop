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

#include "../../DiscoPoP.hpp"

// iterates over all functions in the module and calls 'instrument_function'
// on suitable ones
void DiscoPoP::instrument_module(llvm::Module *module, map<string, string> *trueVarNamesFromMetadataMap, llvm::ModuleAnalysisManager &mam) {
  for (llvm::Module::iterator func_it = module->begin(); func_it != module->end(); ++func_it) {
    llvm::Function *func = &(*func_it);
    std::string fn_name = func->getName().str();
    if (func->isDeclaration() || (strcmp(fn_name.c_str(), "NULL") == 0) || fn_name.find("llvm") != std::string::npos ||
        inlinedFunction(func)) {
      continue;
    }

    llvm::FunctionAnalysisManager &fam = mam.getResult<FunctionAnalysisManagerModuleProxy>(*module).getManager();
    llvm::LoopInfo &loop_info = fam.getResult<llvm::LoopAnalysis>(*func);

    instrument_function(func, trueVarNamesFromMetadataMap, loop_info);
  }
}
