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

#include <cstdint>
#include <vector>

#include "llvm/IR/DataLayout.h"
#include "llvm/IR/Module.h"

#include "DiscoPoP.hpp"

using llvm::AllocaInst;
using llvm::ArrayType;
using llvm::cast;
using llvm::ConstantInt;
using llvm::IRBuilder;
using llvm::Type;
using llvm::Value;

// Instrumentation function inserters.
void DiscoPoP::InstrumentAlloca(AllocaInst* to_instrument) {
  LID const lid = dputil::GetLid(to_instrument, file_id);
  if (lid == 0) {
    return;
  }

  // NOTE: manual memory management using malloc etc. not covered yet!

  IRBuilder<> irb(to_instrument->getNextNode());

  std::vector<Value*> args;
  args.push_back(LidConstant(lid));
  args.push_back(DetermineVariableNameDynamic(to_instrument, ""));

  // Value *startAddr = PtrToIntInst::CreatePointerCast(toInstrument, Int64, "",
  // toInstrument->getNextNonDebugInstruction());
  Value* start_addr = irb.CreatePtrToInt(to_instrument, int64_, "");
  args.push_back(start_addr);

  // the number of elements: of a variable size alloca its operand, of a (multidimensional) array its elements
  Value* num_elements = irb.CreateIntCast(to_instrument->getArraySize(), int64_, false);
  if (!to_instrument->isArrayAllocation()) {
    std::uint64_t array_elements = 1;
    for (Type* type = to_instrument->getAllocatedType(); type->isArrayTy(); type = type->getArrayElementType()) {
      array_elements *= cast<ArrayType>(type)->getNumElements();
    }
    num_elements = ConstantInt::get(int64_, array_elements);
  }

  // the size in bytes as the target lays the type out (structs and padding included), times the operand of a
  // variable size alloca; the runtime assigns [start_addr, end_addr) to the frame of the function
  const std::uint64_t type_size_in_bytes =
      to_instrument->getModule()->getDataLayout().getTypeAllocSize(to_instrument->getAllocatedType()).getFixedValue();
  Value* num_bytes = ConstantInt::get(int64_, type_size_in_bytes);
  if (to_instrument->isArrayAllocation()) {
    num_bytes = irb.CreateMul(irb.CreateIntCast(to_instrument->getArraySize(), int64_, false), num_bytes);
  }
  Value* end_addr = irb.CreateAdd(start_addr, num_bytes);

  args.push_back(end_addr);
  args.push_back(num_bytes);
  args.push_back(num_elements);
  inserted_access_callbacks_[to_instrument] = irb.CreateCall(dp_alloca_, args, "");
}
