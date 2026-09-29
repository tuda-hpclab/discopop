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

#pragma once

#include "Graph.hpp"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/DebugLoc.h"
#include "llvm/IR/Instructions.h"
#include "llvm/Support/Debug.h"
#include <llvm/Support/raw_ostream.h>
#include <string>

#include "DPUtils.hpp"

#define ENTRY 1000000
#define EXIT 2000000

class InstructionCFG : public Graph<Instruction *> {

private:
  InstructionNode<Instruction *> *entry;
  InstructionNode<Instruction *> *exit;
  dputil::VariableNameFinder *VNF;
  set<Instruction *> highlightedInstructionNodes;

  void findAndAddFirstRelevantInstructionInSuccessorBlocks(BasicBlock *BB, Instruction *previousInstruction, std::set<std::pair<BasicBlock*, Instruction*>> *visited);

public:
  InstructionCFG(dputil::VariableNameFinder *_VNF, Function &F);

  InstructionNode<Instruction *> *getEntry() { return entry; }

  InstructionNode<Instruction *> *getExit() { return exit; }

  bool isEntryOrExit(Instruction *I) {
    return Graph::getInstructionNode(I) == entry || Graph::getInstructionNode(I) == exit;
  }

  void highlightInstructionNode(Instruction *instr);

  void dumpToDot(const string targetPath);
};
