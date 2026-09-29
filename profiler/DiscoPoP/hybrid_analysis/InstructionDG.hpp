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

#include "DPUtils.hpp"
#include "InstructionCFG.hpp"
#include "unordered_map"
#include <string>

class InstructionDG : public Graph<Instruction *> {

private:
  dputil::VariableNameFinder *VNF;
  InstructionCFG *CFG;
  set<Instruction *> highlightedInstructionNodes;
  int32_t fid;

  void recursiveDepChecker(set<Instruction *> *checkedInstructions, Instruction *I, Instruction *C);

  void recursiveDepFinder(set<Instruction *> *checkedInstructions, Instruction *I);

public:
  InstructionDG(dputil::VariableNameFinder *_VNF, InstructionCFG *_CFG, int32_t _fid);

  bool edgeIsINIT(Edge<Instruction *> *e);

  string edgeToDPDep(Edge<Instruction *> *e, unordered_map<string, pair<string, string>> &staticValueNameToMemRegIDMap);
  string edgeToInstructionBasedDPDep(Edge<Instruction *> *e, unordered_map<string, pair<string, string>> &staticValueNameToMemRegIDMap);

  void highlightInstructionNode(Instruction *instr);

  void dumpToDot(const string targetPath);

  string getInstructionLine(Instruction *I);

  string getInitEdgeInstructionLine(Edge<Instruction *> *e);

  string getValueNameAndMemRegIDFromEdge(Edge<Instruction *> *e, unordered_map<string, pair<string, string>> &staticValueNameToMemRegIDMap);

};
