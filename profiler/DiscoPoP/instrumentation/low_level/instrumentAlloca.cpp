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

// Instrumentation function inserters.
void DiscoPoP::instrumentAlloca(AllocaInst *toInstrument) {
  LID lid = getLID(toInstrument, fileID);
  if (lid == 0)
    return;

  // NOTE: manual memory management using malloc etc. not covered yet!

  IRBuilder<> IRB(toInstrument->getNextNode());

  vector<Value *> args;
  args.push_back(ConstantInt::get(Int32, lid));
  args.push_back(determineVariableName_dynamic(toInstrument, ""));

  // Value *startAddr = PtrToIntInst::CreatePointerCast(toInstrument, Int64, "",
  // toInstrument->getNextNonDebugInstruction());
  Value *startAddr = IRB.CreatePtrToInt(toInstrument, Int64, "");
  args.push_back(startAddr);

  Value *endAddr = startAddr;
  uint64_t elementSizeInBytes = toInstrument->getAllocatedType()->getScalarSizeInBits() / 8;
  Value *numElements = toInstrument->getOperand(0);
  if (toInstrument->isArrayAllocation()) {
    // endAddr = startAddr + allocated size
    endAddr = IRB.CreateAdd(startAddr, IRB.CreateIntCast(numElements, Int64, true));
  } else if (toInstrument->getAllocatedType()->isArrayTy()) {
    // unpack potentially multidimensional allocations

    Type *typeToParse = toInstrument->getAllocatedType();
    Type *elementType;

    uint64_t tmp_numElements = 1;

    // unpack multidimensional allocations
    while (typeToParse->isArrayTy()) {
      // extract size from current dimension and multiply to numElements
      tmp_numElements *= cast<ArrayType>(typeToParse)->getNumElements();
      // proceed one dimension
      typeToParse = typeToParse->getArrayElementType();
    }
    // typeToParse now contains the element type
    elementType = typeToParse;

    // allocated size = Element size in Bytes * Number of elements
    elementSizeInBytes = elementType->getScalarSizeInBits() / 8;

    // endAddr = startAddr + allocated size
    numElements = ConstantInt::get(Int64, tmp_numElements);
    endAddr = IRB.CreateAdd(startAddr, IRB.CreateIntCast(numElements, Int64, true));
  }

  args.push_back(endAddr);
  args.push_back(
      IRB.CreateMul(IRB.CreateIntCast(numElements, Int64, true), ConstantInt::get(Int64, elementSizeInBytes)));
  args.push_back(IRB.CreateIntCast(numElements, Int64, true));
  IRB.CreateCall(DpAlloca, args, "");
}
