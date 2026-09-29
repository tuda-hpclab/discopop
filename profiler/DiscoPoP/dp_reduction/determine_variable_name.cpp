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

string DiscoPoP::dp_reduction_determineVariableName(Instruction *I, map<string, string> *trueVarNamesFromMetadataMap) {

  assert(I && "Instruction cannot be NULL \n");
  int index = isa<StoreInst>(I) ? 1 : 0;
  Value *operand = I->getOperand(index);

  IRBuilder<> builder(I);

  if (operand == NULL) {
    string retVal = getOrInsertVarName_static("", builder);
    if (trueVarNamesFromMetadataMap->find(retVal) == trueVarNamesFromMetadataMap->end()) {
      return retVal; // not found
    } else {
      return (*trueVarNamesFromMetadataMap)[retVal]; // found
    }
  }

  if (operand->hasName()) {
    //// we've found a global variable
    if (isa<GlobalVariable>(*operand)) {
      string retVal = string(operand->getName());
      if (trueVarNamesFromMetadataMap->find(retVal) == trueVarNamesFromMetadataMap->end()) {
        return retVal; // not found
      } else {
        return (*trueVarNamesFromMetadataMap)[retVal]; // found
      }
    }
    if (isa<GetElementPtrInst>(*operand)) {
      GetElementPtrInst *gep = cast<GetElementPtrInst>(operand);
      Value *ptrOperand = gep->getPointerOperand();
      PointerType *PTy = cast<PointerType>(ptrOperand->getType());

      // we've found a struct/class
      // (2025-10-30) Simplified unpacking of structs for llvm 19 compatibility inside dp_reduction_pointsToStruct
      Type *structType = dp_reduction_pointsToStruct(PTy);
      if (structType && gep->getNumOperands() > 2) {
        Value *constValue = gep->getOperand(2);
        if (constValue && isa<ConstantInt>(*constValue)) {
          ConstantInt *idxPtr = cast<ConstantInt>(gep->getOperand(2));
          uint64_t memberIdx = *(idxPtr->getValue().getRawData());
          if (!(cast<StructType>(structType))->isLiteral()) {
            string strName(structType->getStructName().data());
            map<string, MDNode *>::iterator it = Structs.find(strName);
            if (it != Structs.end()) {
              std::string ret = findStructMemberName_static(it->second, memberIdx, builder);
              if (ret.size() > 0) {
                string retVal = ret;
                if (trueVarNamesFromMetadataMap->find(retVal) == trueVarNamesFromMetadataMap->end()) {
                  return retVal; // not found
                } else {
                  return (*trueVarNamesFromMetadataMap)[retVal]; // found
                }
              } else {
                string retVal = getOrInsertVarName_static("", builder);
                if (trueVarNamesFromMetadataMap->find(retVal) == trueVarNamesFromMetadataMap->end()) {
                  return retVal; // not found
                } else {
                  return (*trueVarNamesFromMetadataMap)[retVal]; // found
                }
              }
            }
          }
        }
      }

      // we've found an array
      // (25-10-30) Note: replaced for LLVM19 compatibility
      // OLD: if (PTy->getPointerElementType()->getTypeID() == Type::ArrayTyID && isa<GetElementPtrInst>(*ptrOperand)) {
      if (isa<GetElementPtrInst>(*ptrOperand)) {
        return dp_reduction_determineVariableName((Instruction *)ptrOperand, trueVarNamesFromMetadataMap);
      }
      return dp_reduction_determineVariableName((Instruction *)gep, trueVarNamesFromMetadataMap);
    }
    string retVal = string(operand->getName().data());
    if (trueVarNamesFromMetadataMap->find(retVal) == trueVarNamesFromMetadataMap->end()) {
      return retVal; // not found
    } else {
      return (*trueVarNamesFromMetadataMap)[retVal]; // found
    }
  }

  if (isa<LoadInst>(*operand) || isa<StoreInst>(*operand)) {
    return dp_reduction_determineVariableName((Instruction *)(operand), trueVarNamesFromMetadataMap);
  }
  // if we cannot determine the name, then return *
  return "*";
}
