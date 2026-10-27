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

#include <string>
#include <vector>

#include "dp_reduction/ReductionInstrumenter.hpp"
#include "utils/profiler_files.hpp"

// Inserts calls to allow for dynamic analysis of the loops.
void dp_reduction::ReductionInstrumenter::InsertFunctions() {
  // insert function calls to monitor the variable's load and store operations
  for (const auto& instruction : instructions_) {
    const int store_line = instruction.store_inst->getDebugLoc().getLine();

    // output information about the reduction variables
    reduction_file_ << " FileID : " << instruction.file_id;
    reduction_file_ << " Loop Line Number : " << instruction.loop_line_nr;
    reduction_file_ << " Reduction Line Number : " << std::to_string(store_line);
    reduction_file_ << " Variable Name : " << instruction.var_name;
    reduction_file_ << " Operation Name : " << instruction.operation << "\n";
  }

  // insert function calls to monitor loop iterations
  std::ofstream loop_metadata_file;
  std::string tmp(dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler"));
  tmp += "/loop_meta.txt";
  loop_metadata_file.open(tmp.data());
  // llvm::ArrayRef<llvm::Type *> loop_incr_fn_args();
  const std::vector<llvm::Type*> loop_incr_fn_args(2, llvm::Type::getInt32Ty(module_.getContext()));

  llvm::FunctionType* loop_incr_fn_type =
      llvm::FunctionType::get(llvm::Type::getVoidTy(module_.getContext()), loop_incr_fn_args, false);
  const llvm::FunctionCallee incr_loop_counter_callee =
      module_.getOrInsertFunction("__dp_loop_incr", loop_incr_fn_type);

  for (const auto& loop_info : loops_) {
    //    llvm::Value *val = llvm::ConstantInt::get(llvm::Type::getInt32Ty(module_.getContext()), loop_id);
    //    llvm::Value *val2 = llvm::ConstantInt::get(llvm::Type::getInt32Ty(module_.getContext()), 0);  // instruction
    //    id will be replaced after assigning unique instruction ids
    // llvm::ArrayRef<llvm::Value *> args(val, val2);
    std::vector<llvm::Value*> args;
    args.push_back(llvm::ConstantInt::get(llvm::Type::getInt32Ty(module_.getContext()), loop_info.loop_id));
    args.push_back(llvm::ConstantInt::get(llvm::Type::getInt32Ty(module_.getContext()),
                                          0));  // instruction id will be replaced after assigning unique

    llvm::CallInst::Create(incr_loop_counter_callee, args, "", loop_info.first_body_instr->getIterator());
    loop_metadata_file << loop_info.file_id << " ";
    loop_metadata_file << loop_info.loop_id << " ";
    loop_metadata_file << loop_info.line_nr << "\n";
  }
  loop_metadata_file.close();

  // Nothing dumps the counters from here any more. __dp_finalize does it, which reaches the
  // modules that do not define main as well and survives a target that leaves through exit().
}
