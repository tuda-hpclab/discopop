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

void DiscoPoP::instrumentDeleteOrFree(CallBase *toInstrument) {
  // add instrumentation for delete instructions or calls to free
  LID lid = getLID(toInstrument, fileID);
  if (lid == 0)
    return;
#if LLVM_VERSION_MAJOR >= 22
  IRBuilder<> IRB(toInstrument->getNextNode());
#else
  IRBuilder<> IRB(toInstrument->getNextNonDebugInstruction());
#endif

  vector<Value *> args;
  args.push_back(ConstantInt::get(Int32, lid));

#if LLVM_VERSION_MAJOR >= 22
  Value *startAddr =
      PtrToIntInst::CreatePointerCast(toInstrument->getArgOperand(0), Int64, "", toInstrument->getNextNode()->getIterator());
#else
  Value *startAddr =
      PtrToIntInst::CreatePointerCast(toInstrument->getArgOperand(0), Int64, "", toInstrument->getNextNode());
#endif

  args.push_back(startAddr);

  IRB.CreateCall(DpDelete, args, "");
}
