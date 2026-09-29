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

void DiscoPoP::instrumentFuncEntry(Function &F) {
  BasicBlock &entryBB = F.getEntryBlock();
  LID lid = 0;
  int32_t isStart = 0;

  StringRef fn = F.getName();
  if (fn.str() == "main"){
    isStart = 1;
    // insert 'allocations' of global variables
    Instruction *insertBefore = &*entryBB.begin();

    auto tmp_end = F.getParent()->global_end();
    tmp_end--; // necessary, since the list of Globals is modified when e.g. new
               // strings are created.
    for (auto Global_it = F.getParent()->global_begin(); Global_it != tmp_end; Global_it++) {
      // ignore globals which make use of "Appending Linkage", since they are
      // system internal and do not behave like regular values. An example for
      // such a value is @llvm.global_ctors
      if (cast<GlobalVariable>(&*Global_it)->hasAppendingLinkage()) {
        continue;
      }

      IRBuilder<> IRB(insertBefore->getNextNode());

      vector<Value *> args;
      args.push_back(ConstantInt::get(Int32, lid));
      args.push_back(getOrInsertVarName_dynamic(Global_it->getName().str(), IRB));

      // Value *startAddr = PtrToIntInst::CreatePointerCast(toInstrument, Int64,
      // "", toInstrument->getNextNonDebugInstruction());
      Value *startAddr = IRB.CreatePtrToInt(cast<Value>(&*Global_it), Int64, "");
      args.push_back(startAddr);

      Value *endAddr = startAddr;
      uint64_t numElements = 1;
      uint64_t allocatedSize = Global_it->getValueType()->getScalarSizeInBits();
      if (Global_it->getValueType()->isArrayTy()) {
        // unpack potentially multidimensional allocations
        Type *typeToParse = Global_it->getValueType();
        Type *elementType;

        // unpack multidimensional allocations
        while (typeToParse->isArrayTy()) {
          // extract size from current dimension and multiply to numElements
          numElements *= cast<ArrayType>(typeToParse)->getNumElements();
          // proceed one dimension
          typeToParse = typeToParse->getArrayElementType();
        }
        // typeToParse now contains the element type
        elementType = typeToParse;

        // allocated size = Element size in Bytes * Number of elements
        auto elementSizeInBytes = elementType->getScalarSizeInBits() / 8;
        allocatedSize = elementSizeInBytes * numElements;

        // endAddr = startAddr + allocated size
        endAddr = IRB.CreateAdd(startAddr, ConstantInt::get(Int64, allocatedSize));
      }

      args.push_back(endAddr);
      args.push_back(ConstantInt::get(Int64, allocatedSize));
      args.push_back(ConstantInt::get(Int64, numElements));
      // REMOVED TO FIX INCORRECT STACK ADDRESS TRACKING
      // TODO: maybe replace with explicit registration of global variables
      // IRB.CreateCall(DpAlloca, args, "");
    }
  }

  // We always want to insert __dp_func_entry at the beginning
  // of the basic block, but we need the first valid LID to
  // get the entry line of the function.
  for (BasicBlock::iterator BI = entryBB.begin(), EI = entryBB.end(); BI != EI; ++BI) {
    lid = getLID(&*BI, fileID);
    if (lid > 0 && !isa<PHINode>(BI)) {
      IRBuilder<> IRB(&*entryBB.begin());
      IRB.CreateCall(DpFuncEntry, {ConstantInt::get(Int32, lid), ConstantInt::get(Int32, isStart)});
      if (DP_DEBUG) {
        errs() << "DiscoPoP: funcEntry instrumented\n";
      }
      break;
    }
  }
  assert((lid > 0) && "Function entry is not instrumented because LID are all "
                      "invalid for the entry block.");
}
