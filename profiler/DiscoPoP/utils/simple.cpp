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

Type *DiscoPoP::pointsToStruct(PointerType *PTy) {
  assert(PTy);
  Type *structType = PTy;
  // (2025-10-30) Simplified for llvm 19 compatibility
  /*
  if (PTy->getTypeID() == Type::PointerTyID) {
    while (structType->getTypeID() == Type::PointerTyID) {
      structType = cast<PointerType>(structType)->getElementType();
    }
  }
  */
  return structType->getTypeID() == Type::StructTyID ? structType : NULL;
}

Value *DiscoPoP::findStructMemberName(MDNode *structNode, unsigned idx, IRBuilder<> &builder) {
  assert(structNode);
  assert(structNode->getOperand(10));
  MDNode *memberListNodes = cast<MDNode>(structNode->getOperand(10));
  if (idx < memberListNodes->getNumOperands()) {
    assert(memberListNodes->getOperand(idx));
    MDNode *member = cast<MDNode>(memberListNodes->getOperand(idx));
    if (member->getOperand(3)) {
      return getOrInsertVarName_dynamic(dyn_cast<MDString>(member->getOperand(3))->getString().str(), builder);
    }
  }
  return NULL;
}

DIGlobalVariable *DiscoPoP::findDbgGlobalDeclare(GlobalVariable *v) {
  assert(v && "Global variable cannot be null");
  for (set<DIGlobalVariable *>::iterator it = GlobalVars.begin(); it != GlobalVars.end(); ++it) {
    if ((*it)->getDisplayName() == v->getName())
      return *it;
  }
  return NULL;
}

void DiscoPoP::collectDebugInfo() {
  if (NamedMDNode *CU_Nodes = ThisModule->getNamedMetadata("llvm.dbg.cu")) {
    for (unsigned i = 0, e = CU_Nodes->getNumOperands(); i != e; ++i) {
      DICompileUnit *CU = cast<DICompileUnit>(CU_Nodes->getOperand(i));
      auto GVs = CU->getGlobalVariables();
      for (unsigned i = 0, e = GVs.size(); i < e; ++i) {
        DIGlobalVariable *DIG = GVs[i]->getVariable();
        if (DIG) {
          GlobalVars.insert(DIG);
        }
      }
    }
  }
}

bool DiscoPoP::isaCallOrInvoke(Instruction *BI) {
  return (BI != NULL) && ((isa<CallInst>(BI) && (!isa<DbgDeclareInst>(BI))) || isa<InvokeInst>(BI));
}

bool DiscoPoP::sanityCheck(BasicBlock *BB) {
  LID lid;
  for (BasicBlock::iterator BI = BB->begin(), EI = BB->end(); BI != EI; ++BI) {
    lid = getLID(&*BI, fileID);
    if (lid > 0) {
      return true;
    }
  }
  if (DP_VERBOSE) {
    errs() << "WARNING: basic block " << BB << " doesn't contain valid LID.\n";
  }
  return false;
}

bool DiscoPoP::check_value_usage(llvm::Value *parentValue, llvm::Value *searchedValue) {
  // Return true, if searchedValue is used within the computation of parentValue
  if (parentValue == searchedValue) {
    return true;
  }

  // check operands recursively, if parentValue is not a constant yet
  if (isa<Constant>(parentValue)) {
    return false;
  }
  // if parentValue is not an Instruction, the value can not be used, thus
  // return false
  if (!isa<Instruction>(parentValue)) {
    errs() << "parentValue not an Instruction.\n";
    return false;
  }

  llvm::Instruction *parentInstruction = cast<Instruction>(parentValue);
  for (unsigned int idx = 0; idx < parentInstruction->getNumOperands(); idx++) {
    if (check_value_usage(parentInstruction->getOperand(idx), searchedValue)) {
      return true;
    }
  }

  return false;
}

bool DiscoPoP::inlinedFunction(Function *F) {
  for (Function::iterator FI = F->begin(), FE = F->end(); FI != FE; ++FI) {
    for (BasicBlock::iterator BI = FI->begin(), E = FI->end(); BI != E; ++BI) {
      if (DbgDeclareInst *DI = dyn_cast<DbgDeclareInst>(BI)) {
        if (DI->getDebugLoc()->getInlinedAt())
          return true;
      }
    }
  }
  return false;
}

bool DiscoPoP::isRecursive(Function &F, CallGraph &CG) {
  auto callNode = CG[&F];
  for (unsigned i = 0; i < callNode->size(); i++) {
    if ((*callNode)[i]->getFunction() == &F)
      return true;
  }
  return false;
}

void DiscoPoP::fillStartEndLineNumbers(Node *root, LoopInfo &LI) {
  if (root->type != nodeTypes::cu) {
    int start = -1, end = -1;

    if (root->type == nodeTypes::loop) {
      for (auto i : root->childrenNodes) {
        if (i->type == nodeTypes::cu) {
          Loop *loop = LI.getLoopFor(i->BB);
          DebugLoc dl = loop->getStartLoc();
          LID lid = 0;
          lid = (fileID << LIDSIZE) + dl->getLine();
          loopStartLines[root->ID] = dputil::decodeLID(lid);
          break;
        }
      }
    }
    findStartEndLineNumbers(root, start, end);

    root->startLine = start;
    root->endLine = end;
  }

  for (auto i : root->childrenNodes) {
    fillStartEndLineNumbers(i, LI);
  }
}

void DiscoPoP::findStartEndLineNumbers(Node *root, int &start, int &end) {
  if (root->type == nodeTypes::cu) {
    if (start == -1 || start > root->startLine) {
      start = root->startLine;
    }

    if (end < root->endLine) {
      end = root->endLine;
    }
  }

  for (auto i : root->childrenNodes) {
    findStartEndLineNumbers(i, start, end);
  }
}

void DiscoPoP::getFunctionReturnLines(Region *TopRegion, Node *root) {
  int lid = 0;
  for (Region::block_iterator bb = TopRegion->block_begin(); bb != TopRegion->block_end(); ++bb) {
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      if (isa<ReturnInst>(instruction)) {
        lid = getLID(&*instruction, fileID);
        if (lid > 0)
          root->returnLines.insert(lid);
      }
    }
  }
}


int32_t DiscoPoP::get_or_register_loop_id(llvm::Loop* L){
  // Check if loop is already registered
    int32_t tmp_loop_id;
    auto pos = loop_to_id.find(L);
    if (pos != loop_to_id.end()) {
        // L found. Return loop id
        tmp_loop_id = pos->second;
    } else {
        // L not found. register loop id
        tmp_loop_id = loopID;
        loop_to_id.insert(make_pair(L, tmp_loop_id));
        loopID++;
    }
    return tmp_loop_id;
}
