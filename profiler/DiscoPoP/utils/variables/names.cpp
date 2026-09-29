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

string DiscoPoP::getOrInsertVarName_static(string varName, IRBuilder<> &builder) {
  Value *valName = NULL;
  // remove .addr if added. Replaced by the GEPRESULT_ tag
  if (varName.find(".addr") != std::string::npos){
    varName.erase(varName.find(".addr"), 5);
  }

  std::string vName = varName;
  map<string, Value *>::iterator pair = VarNames.find(varName);
  if (pair == VarNames.end()) {
    valName = builder.CreateGlobalStringPtr(StringRef(varName.c_str()), ".str");

    VarNames[varName] = valName;
  } else {
    vName = pair->first;
  }

  return vName;
}

Value *DiscoPoP::getOrInsertVarName_dynamic(string varName, IRBuilder<> &builder) {
  // remove .addr if added. Replaced by the GEPRESULT_ tag
  if (varName.find(".addr") != std::string::npos){
    varName.erase(varName.find(".addr"), 5);
  }

  // 26.08.2022 Lukas
  // update varName with original varName from Metadata
  if (trueVarNamesFromMetadataMap.find(varName) == trueVarNamesFromMetadataMap.end()) {
    // not found, do nothing
  } else {
    // found, update varName
    varName = trueVarNamesFromMetadataMap[varName];
  }

  Value *vName = NULL;
  map<string, Value *>::iterator pair = VarNames.find(varName);
  if (pair == VarNames.end()) {
    vName = builder.CreateGlobalStringPtr(StringRef(varName.c_str()), ".str");
    VarNames[varName] = vName;
  } else {
    vName = pair->second;
  }
  return vName;
}

string DiscoPoP::determineVariableName_static(Instruction *I, bool &isGlobalVariable /*=defaultIsGlobalVariableValue*/,
                                              bool disable_MetadataMap, string prefix) {

  assert(I && "Instruction cannot be NULL \n");
  int index = isa<StoreInst>(I) ? 1 : 0;
  Value *operand = I->getOperand(index);

  IRBuilder<> builder(I);

  if (operand == NULL) {
    string retVal = getOrInsertVarName_static("", builder);
    if (trueVarNamesFromMetadataMap.find(retVal) == trueVarNamesFromMetadataMap.end() || disable_MetadataMap) {
      return retVal; // not found
    } else {
      return trueVarNamesFromMetadataMap[retVal]; // found
    }
  }

  if (operand->hasName()) {
    //// we've found a global variable
    if (isa<GlobalVariable>(*operand)) {
      // MOHAMMAD ADDED THIS FOR CHECKING
      isGlobalVariable = true;
      string retVal = string(operand->getName());
      if (trueVarNamesFromMetadataMap.find(retVal) == trueVarNamesFromMetadataMap.end() || disable_MetadataMap) {
        return retVal; // not found
      } else {
        return trueVarNamesFromMetadataMap[retVal]; // found
      }
    }
    if (isa<GetElementPtrInst>(*operand)) {
      GetElementPtrInst *gep = cast<GetElementPtrInst>(operand);
      Value *ptrOperand = gep->getPointerOperand();
      PointerType *PTy = cast<PointerType>(ptrOperand->getType());

      // we've found a struct/class
      Type *structType = pointsToStruct(PTy);
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
                if (trueVarNamesFromMetadataMap.find(retVal) == trueVarNamesFromMetadataMap.end() ||
                    disable_MetadataMap) {
                  return retVal; // not found
                } else {
                  return trueVarNamesFromMetadataMap[retVal]; // found
                }
              } else {
                string retVal = getOrInsertVarName_static("", builder);
                if (trueVarNamesFromMetadataMap.find(retVal) == trueVarNamesFromMetadataMap.end() ||
                    disable_MetadataMap) {
                  return retVal; // not found
                } else {
                  return trueVarNamesFromMetadataMap[retVal]; // found
                }
                // return ret;
              }
            }
          }
        }
      }

      // we've found an array
      // NOTE (25-10-30) simplified for LLVM 19 compatibility
      // OLD: if (PTy->getPointerElementType()->getTypeID() == Type::ArrayTyID && isa<GetElementPtrInst>(*ptrOperand)) {
      if (isa<GetElementPtrInst>(*ptrOperand)) {
        return determineVariableName_static((Instruction *)ptrOperand, isGlobalVariable, false, prefix);
      }
      return determineVariableName_static((Instruction *)gep, isGlobalVariable, false, "GEPRESULT_" + prefix);
    }
    string retVal = string(operand->getName().data());
    if (trueVarNamesFromMetadataMap.find(retVal) == trueVarNamesFromMetadataMap.end() || disable_MetadataMap) {
      return retVal; // not found
    } else {
      return trueVarNamesFromMetadataMap[retVal]; // found
    }
    // return getOrInsertVarName(string(operand->getName().data()), builder);
  }

  if (isa<LoadInst>(*operand) || isa<StoreInst>(*operand)) {
    return determineVariableName_static((Instruction *)(operand), isGlobalVariable, false, prefix);
  }
  // if we cannot determine the name, then return *
  return ""; // getOrInsertVarName("*", builder);
}

Value *DiscoPoP::determineVariableName_dynamic(Instruction *const I, string prefix) {
  assert(I && "Instruction cannot be NULL \n");
  int index = isa<StoreInst>(I) ? 1 : 0;
  Value *operand = I->getOperand(index);

  IRBuilder<> builder(I);

  if (operand == NULL) {
    return getOrInsertVarName_dynamic("*", builder);
  }

  if (operand->hasName()) {
    // we've found a global variable
    if (isa<GlobalVariable>(*operand)) {
      DIGlobalVariable *gv = findDbgGlobalDeclare(cast<GlobalVariable>(operand));
      if (gv != NULL) {
        return getOrInsertVarName_dynamic(prefix +  string(gv->getDisplayName().data()), builder);
      }
    }
    if (isa<GetElementPtrInst>(*operand)) {
      GetElementPtrInst *gep = cast<GetElementPtrInst>(operand);
      Value *ptrOperand = gep->getPointerOperand();
      PointerType *PTy = cast<PointerType>(ptrOperand->getType());

      // we've found a struct/class
      Type *structType = pointsToStruct(PTy);
      if (structType && gep->getNumOperands() > 2) {
        Value *constValue = gep->getOperand(2);
        if (constValue && isa<ConstantInt>(*constValue)) {
          ConstantInt *idxPtr = cast<ConstantInt>(gep->getOperand(2));
          uint64_t memberIdx = *(idxPtr->getValue().getRawData());

          StructType *STy = cast<StructType>(structType);
          if (!STy->isLiteral()) {
            string strName(structType->getStructName().data());
            map<string, MDNode *>::iterator it = Structs.find(strName);
            if (it != Structs.end()) {
              Value *ret = findStructMemberName(it->second, memberIdx, builder);
              if (ret)
                return ret;
            }
          }
        }
      }

      // we've found an array
      // (2025-10-30) Simplified check for array type for llvm 19 compatibility
      //if (PTy->getPointerElementType()->getTypeID() == Type::ArrayTyID && isa<GetElementPtrInst>(*ptrOperand)) {
      if (isa<GetElementPtrInst>(*ptrOperand)) {
        return determineVariableName_dynamic((Instruction *)ptrOperand, prefix);
      }
      return determineVariableName_dynamic((Instruction *)gep, "GEPRESULT_"+prefix);
    }
    return getOrInsertVarName_dynamic(prefix + string(operand->getName().data()), builder);
  }

  if (isa<LoadInst>(*operand) || isa<StoreInst>(*operand)) {
    return determineVariableName_dynamic((Instruction *)(operand), prefix);
  }
  if (isa<AllocaInst>(I)) {
    return getOrInsertVarName_dynamic(prefix + I->getName().str(), builder);
  }
  // if we cannot determine the name, then return *
  return getOrInsertVarName_dynamic(prefix +  "*", builder);
}

void DiscoPoP::getTrueVarNamesFromMetadata(Region *TopRegion, Node *root,
                                           std::map<string, string> *trueVarNamesFromMetadataMap) {
  // check for deb_declare in Region
  // get IRVarName from first operand
  // get SRCVarName from second operand
  // update trueVarNamesFromMetadataMap
  for(auto BB : TopRegion->blocks()){
    for(auto &inst : BB->instructionsWithoutDebug()){
      auto dbg_record_range = inst.getDbgRecordRange();
      auto dbg_variable_range = filterDbgVars(dbg_record_range);
      for (DbgVariableRecord &DVR : dbg_variable_range) {
        std::string IRVarName = DVR.getValue()->getName().str();
        std::string SRCVarName = DVR.getVariable()->getName().str();
        // add to trueVarNamesFromMetadataMap
        // overwrite entry if already existing
        if (trueVarNamesFromMetadataMap->find(IRVarName) == trueVarNamesFromMetadataMap->end()) {
          // not found
          trueVarNamesFromMetadataMap->insert(std::pair<string, string>(IRVarName, SRCVarName));
        } else {
          // found
          (*trueVarNamesFromMetadataMap)[IRVarName] = SRCVarName;
        }
      }
    }
  }
}
