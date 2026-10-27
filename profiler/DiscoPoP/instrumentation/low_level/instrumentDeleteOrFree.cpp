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

#include <vector>

#include "DiscoPoP.hpp"
#include "llvm_compat.hpp"

using llvm::CallBase;
using llvm::IRBuilder;
using llvm::PtrToIntInst;
using llvm::Value;

void DiscoPoP::InstrumentDeleteOrFree(CallBase* to_instrument) {
  // add instrumentation for delete instructions or calls to free
  LID const lid = dputil::GetLid(to_instrument, file_id);
  if (lid == 0) {
    return;
  }
  IRBuilder<> irb(llvmcompat::NextInstruction(to_instrument));

  std::vector<Value*> args;
  args.push_back(LidConstant(lid));

  Value* start_addr = PtrToIntInst::CreatePointerCast(to_instrument->getArgOperand(0), int64_, "",
                                                      to_instrument->getNextNode()->getIterator());

  args.push_back(start_addr);

  irb.CreateCall(dp_delete_, args, "");
}
