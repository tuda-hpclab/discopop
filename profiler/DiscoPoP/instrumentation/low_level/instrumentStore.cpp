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

#include "DiscoPoP.hpp"
#include "llvm_compat.hpp"

using llvm::BinaryOperator;
using llvm::CallInst;
using llvm::Constant;
using llvm::ConstantInt;
using llvm::GlobalVariable;
using llvm::Instruction;
using llvm::LoadInst;
using llvm::PtrToIntInst;
using llvm::StoreInst;
using llvm::Twine;
using llvm::Value;

void DiscoPoP::InstrumentStore(StoreInst* to_instrument, std::int32_t llvm_ir_instruction_id) {
  LID const lid = dputil::GetLid(to_instrument, file_id);
  if (lid == 0) {
    return;
  }

  std::vector<Value*> args;
  args.push_back(ConstantInt::get(int64_, llvm_ir_instruction_id));

  Value* mem_addr =
      PtrToIntInst::CreatePointerCast(to_instrument->getPointerOperand(), int64_, "", to_instrument->getIterator());
  args.push_back(mem_addr);

  args.push_back(DetermineVariableNameDynamic(to_instrument, ""));

#ifdef SKIP_DUP_INSTR
  std::string name = "S" + std::to_string(unique_num_);

  GlobalVariable* addrTracker = new GlobalVariable(*this->this_module_,
                                                   int64_,  // trackerType
                                                   false, GlobalVariable::PrivateLinkage,
                                                   Constant::getNullValue(int64_),  // trackerType
                                                   name);
  GlobalVariable* countTracker = new GlobalVariable(*this->this_module_, int64_, false, GlobalVariable::PrivateLinkage,
                                                    Constant::getNullValue(int64_), name + "count");
  unique_num_++;

  // Load current values before instr
  LoadInst* currentAddrTracker = new LoadInst::LoadInst(addrTracker, Twine(), toInstrument);
  LoadInst* currentCount = new LoadInst::LoadInst(countTracker, Twine(), toInstrument);

  // add instr before before
  args.push_back(currentAddrTracker);
  args.push_back(currentCount);
#endif

  CallInst* callback = CallInst::Create(dp_write_, args, "", to_instrument->getIterator());
  inserted_access_callbacks_[to_instrument] = callback;

#ifdef SKIP_DUP_INSTR
  // Post instrumentation call
  // Create updates
  StoreInst* addrUpdate = new StoreInst::StoreInst(memAddr, addrTracker);
  BinaryOperator::BinaryOperator* incCount =
      BinaryOperator::Create(Instruction::Add, currentCount, ConstantInt::get(int64_, 1));
  StoreInst* countUpdate = new StoreInst::StoreInst(incCount, countTracker);

  // add updates after before
  llvmcompat::InsertAfter(addrUpdate, to_instrument);
  llvmcompat::InsertAfter(incCount, to_instrument);
  llvmcompat::InsertAfter(countUpdate, incCount);
#endif
}
