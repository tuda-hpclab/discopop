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

  Value* end_addr = start_addr;
  std::uint64_t element_size_in_bytes = to_instrument->getAllocatedType()->getScalarSizeInBits() / 8;
  Value* num_elements = to_instrument->getOperand(0);
  if (to_instrument->isArrayAllocation()) {
    // endAddr = startAddr + allocated size
    end_addr = irb.CreateAdd(start_addr, irb.CreateIntCast(num_elements, int64_, true));
  } else if (to_instrument->getAllocatedType()->isArrayTy()) {
    // unpack potentially multidimensional allocations

    Type* type_to_parse = to_instrument->getAllocatedType();
    Type* element_type;

    std::uint64_t tmp_num_elements = 1;

    // unpack multidimensional allocations
    while (type_to_parse->isArrayTy()) {
      // extract size from current dimension and multiply to numElements
      tmp_num_elements *= cast<ArrayType>(type_to_parse)->getNumElements();
      // proceed one dimension
      type_to_parse = type_to_parse->getArrayElementType();
    }
    // typeToParse now contains the element type
    element_type = type_to_parse;

    // allocated size = Element size in Bytes * Number of elements
    element_size_in_bytes = element_type->getScalarSizeInBits() / 8;

    // endAddr = startAddr + allocated size
    num_elements = ConstantInt::get(int64_, tmp_num_elements);
    end_addr = irb.CreateAdd(start_addr, irb.CreateIntCast(num_elements, int64_, true));
  }

  args.push_back(end_addr);
  args.push_back(
      irb.CreateMul(irb.CreateIntCast(num_elements, int64_, true), ConstantInt::get(int64_, element_size_in_bytes)));
  args.push_back(irb.CreateIntCast(num_elements, int64_, true));
  inserted_access_callbacks_[to_instrument] = irb.CreateCall(dp_alloca_, args, "");
}
