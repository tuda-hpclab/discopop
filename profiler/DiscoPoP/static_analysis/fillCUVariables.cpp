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

void DiscoPoP::fillCUVariables(Region *TopRegion, set<string> &globalVariablesSet, vector<CU *> &CUVector,
                               map<string, vector<CU *>> &BBIDToCUIDsMap) {
  int lid;
  string varName, varType, varDefLine;
  bool isGlobalVar = false;
  // Changed TerminatorInst to Instuction
  const Instruction *TInst;
  string successorBB;

  for (Region::block_iterator bb = TopRegion->block_begin(); bb != TopRegion->block_end(); ++bb) {
    CU *lastCU = BBIDToCUIDsMap[bb->getName().str()].back(); // get the last CU in the basic block
    // get all successor basic blocks for bb
    TInst = bb->getTerminator();
    for (unsigned i = 0, nSucc = TInst->getNumSuccessors(); i < nSucc; ++i) {
      // get the name of successor basicBlock
      successorBB = TInst->getSuccessor(i)->getName().str();
      // get the first CU of the successor basicBlock and record its ID in
      // current CU's successorCUs
      lastCU->successorCUs.push_back(BBIDToCUIDsMap[successorBB].front()->ID);
    }

    auto bbCU = BBIDToCUIDsMap[bb->getName().str()].begin();
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      if (isa<LoadInst>(instruction) || isa<StoreInst>(instruction)) {
        // NOTE: changed 'instruction' to '&*instruction'
        lid = getLID(&*instruction, fileID);
        if (lid == 0)
          continue;
        // NOTE: changed 'instruction' to '&*instruction', next 2 lines
        varName = determineVariableName_static(&*instruction, isGlobalVar, false, "");
        varType = determineVariableType(&*instruction);

        // (2025-10-30) removed due to llvm 19 compatibility
        /*
        int index = isa<StoreInst>(&*instruction) ? 1 : 0;

        Type *variableType = (&*instruction)->getOperand(index)->getType();
        while (variableType->isPointerTy()) {
          variableType = variableType->getPointerElementType();
        }
        string varSizeInBytes = to_string(variableType->getScalarSizeInBits() / 8);
        */

        varDefLine = determineVariableDefLine(&*instruction);

        bool readAccess = isa<LoadInst>(instruction);
        bool writeAccess = isa<StoreInst>(instruction);

        Variable v(varName, varType, varDefLine, readAccess, writeAccess);

        if (lid > (*bbCU)->endLine) {
          bbCU = next(bbCU, 1);
        }
        if (globalVariablesSet.count(varName) || programGlobalVariablesSet.count(varName)) {
          (*bbCU)->globalVariableNames.insert(v);
        } else {
          (*bbCU)->localVariableNames.insert(v);
        }
      }
    }
  }
}
