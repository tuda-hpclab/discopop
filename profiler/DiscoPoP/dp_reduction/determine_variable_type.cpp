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

#include "../DiscoPoP.hpp"

string DiscoPoP::dp_reduction_determineVariableType(Instruction *I) {
  string s = "";
  string type_str;
  int index = isa<StoreInst>(I) ? 1 : 0;
  raw_string_ostream rso(type_str);
  (*((I->getOperand(index))->getType())).print(rso);

  Value *operand = I->getOperand(index);

  if (operand->hasName()) {
    if (isa<GetElementPtrInst>(*operand)) {
      GetElementPtrInst *gep = cast<GetElementPtrInst>(operand);
      // we've found a struct/class
      // (2025-10-30) check of struct type omitted for LLVM 19 compatibility
      //Value *ptrOperand = gep->getPointerOperand();
      //PointerType *PTy = cast<PointerType>(ptrOperand->getType());
      //Type *structType = dp_reduction_pointsToStruct(PTy);
      //if (structType && gep->getNumOperands() > 2) {
      if (gep->getNumOperands() > 2) {
        s = "STRUCT,";
      }
      // we've found an array
      // check if previous instruction is a GEP aswell. If so, an Array has
      // been found (e.g. double**)
      Value *prevInst = cast<Instruction>(gep)->getOperand(0);
      if (isa<GetElementPtrInst>(prevInst)) {
        s = "ARRAY,";
      } else if (prevInst->getType()->isPointerTy()) {
        s = "ARRAY,";
      }
    }
  }

  s = s + rso.str();
  return s;
}
