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

#include "InstructionDG.hpp"

#include "DPUtils.hpp"

InstructionDG::InstructionDG(dputil::VariableNameFinder *_VNF, InstructionCFG *_CFG, int32_t _fid)
    : VNF(_VNF), CFG(_CFG), fid(_fid) {
  for (auto edge : CFG->getInEdges(CFG->getExit())) {
    // check for nullptr
    if (edge->getSrc()) {
      recursiveDepFinder(new set<Instruction *>(), edge->getSrc()->getItem());
    }
  }
}

void InstructionDG::recursiveDepChecker(set<Instruction *> *checkedInstructions, Instruction *I, Instruction *C) {
  if (CFG->isEntryOrExit(C))
    return;
  checkedInstructions->insert(C);
  Value *V, *W;
  if (isa<AllocaInst>(I))
    V = dyn_cast<Value>(I);
  else
    V = I->getOperand(isa<StoreInst>(I) ? 1 : 0);

  if (isa<AllocaInst>(C))
    W = dyn_cast<Value>(C);
  else
    W = C->getOperand(isa<StoreInst>(C) ? 1 : 0);

  if (V == W && (isa<StoreInst>(I) || isa<StoreInst>(C))) {
    Graph::addEdge(I, C);
    return;
  }
  for (auto edge : CFG->getInEdges(C))
    if (checkedInstructions->find(edge->getSrc()->getItem()) == checkedInstructions->end())
      recursiveDepChecker(checkedInstructions, I, edge->getSrc()->getItem());
}

void InstructionDG::recursiveDepFinder(set<Instruction *> *checkedInstructions, Instruction *I) {
  if (CFG->isEntryOrExit(I) || checkedInstructions->find(I) != checkedInstructions->end())
    return;
  checkedInstructions->insert(I);
  if (isa<StoreInst>(I) || isa<LoadInst>(I))
    Graph::addInstructionNode(I);
  for (auto edge : CFG->getInEdges(I)) {
    if (isa<StoreInst>(I) || isa<LoadInst>(I)) {
      recursiveDepChecker(new set<Instruction *>(), I, edge->getSrc()->getItem());
    }
    recursiveDepFinder(checkedInstructions, edge->getSrc()->getItem());
  }
}

void InstructionDG::highlightInstructionNode(Instruction *instr) { highlightedInstructionNodes.insert(instr); }

string InstructionDG::getInstructionLine(Instruction *I) {
  if (DebugLoc dl = I->getDebugLoc()) {
    return to_string(dl->getLine());
  } else {
    return to_string(I->getFunction()->getSubprogram()->getLine());
  }
}

bool InstructionDG::edgeIsINIT(Edge<Instruction *> *e){
  Instruction *J = e->getDst()->getItem();

  if(isa<AllocaInst>(J)){
    return true;
  }
  return false;
}

string InstructionDG::getInitEdgeInstructionLine(Edge<Instruction *> *e){
  return getInstructionLine(e->getSrc()->getItem());
}

string InstructionDG::getValueNameAndMemRegIDFromEdge(Edge<Instruction *> *e, unordered_map<string, pair<string, string>> &staticValueNameToMemRegIDMap){
  Instruction *I = e->getSrc()->getItem();
  return staticValueNameToMemRegIDMap[VNF->getVarName(I)].first + "(" + staticValueNameToMemRegIDMap[VNF->getVarName(I)].second + ")";
}

string InstructionDG::edgeToDPDep(Edge<Instruction *> *e,
                                  unordered_map<string, pair<string, string>> &staticValueNameToMemRegIDMap) {
  // staticValueNameToMemRegIDMap maps: <SSA variable name> TO (original
  // variable name, statically assigned MemReg ID)
  Instruction *I = e->getSrc()->getItem();
  Instruction *J = e->getDst()->getItem();

  string depType;
  if (isa<AllocaInst>(J)) {
    depType = "INIT";
    return to_string(fid) + ":" + getInstructionLine(I) + " " + "NOM" + " " + depType + " *|" +
           staticValueNameToMemRegIDMap[VNF->getVarName(I)]
               .first // use original variable name instead of LLVM IR SSA name
           + "(" + staticValueNameToMemRegIDMap[VNF->getVarName(I)].second + ")";
  } else if (DebugLoc dl = J->getDebugLoc()) {
    depType = (isa<LoadInst>(I) ? string("R") : string("W")) + "A" + (isa<LoadInst>(J) ? string("R") : string("W"));
    return to_string(fid) + ":" + getInstructionLine(I) + " " + "NOM" + " " + depType + " " + to_string(fid) + ":" +
           getInstructionLine(J) + "|" +
           staticValueNameToMemRegIDMap[VNF->getVarName(I)]
               .first // use original variable name instead of LLVM IR SSA name
           + "(" + staticValueNameToMemRegIDMap[VNF->getVarName(I)].second + ")";
  } else {
    depType = (isa<LoadInst>(I) ? string("R") : string("W")) + "A" + (isa<LoadInst>(J) ? string("R") : string("W"));
    return to_string(fid) + ":" + getInstructionLine(I) + " " + "NOM" + " " + depType + " " + to_string(fid) + ":" +
           getInstructionLine(J) + "|" +
           staticValueNameToMemRegIDMap[VNF->getVarName(I)]
               .first // use original variable name instead of LLVM IR SSA name
           + "(" + staticValueNameToMemRegIDMap[VNF->getVarName(I)].second + ")";
  }
}

string InstructionDG::edgeToInstructionBasedDPDep(Edge<Instruction *> *e,
                                  unordered_map<string, pair<string, string>> &staticValueNameToMemRegIDMap) {
  // staticValueNameToMemRegIDMap maps: <SSA variable name> TO (original
  // variable name, statically assigned MemReg ID)
  Instruction *I = e->getSrc()->getItem();
  Instruction *J = e->getDst()->getItem();

  // get unique instruction ids from metadata
  MDNode *N_I = I->getMetadata("dp.md.instr.id");
  std::string unique_instruction_id_I = cast< MDString >(N_I->getOperand(0))->getString().str();
  // cleanup metadata string to get the pure id
  unique_instruction_id_I.replace(0, 15, "");  // replaces "dp.md.instr.id:" with ""

  MDNode *N_J = J->getMetadata("dp.md.instr.id");
  std::string unique_instruction_id_J = cast< MDString >(N_J->getOperand(0))->getString().str();
  // cleanup metadata string to get the pure id
  unique_instruction_id_J.replace(0, 15, "");  // replaces "dp.md.instr.id:" with ""

  string depType;
  if (isa<AllocaInst>(J)) {
    depType = "INIT";
    return unique_instruction_id_I + " " + "NOM" + " " + depType + " *|" +
           staticValueNameToMemRegIDMap[VNF->getVarName(I)]
               .first // use original variable name instead of LLVM IR SSA name
           + "(" + staticValueNameToMemRegIDMap[VNF->getVarName(I)].second + ")";
  } else if (DebugLoc dl = J->getDebugLoc()) {
    depType = (isa<LoadInst>(I) ? string("R") : string("W")) + "A" + (isa<LoadInst>(J) ? string("R") : string("W"));
    return unique_instruction_id_I + " " + "NOM" + " " + depType + " " + unique_instruction_id_J + "|" +
           staticValueNameToMemRegIDMap[VNF->getVarName(I)]
               .first // use original variable name instead of LLVM IR SSA name
           + "(" + staticValueNameToMemRegIDMap[VNF->getVarName(I)].second + ")";
  } else {
    depType = (isa<LoadInst>(I) ? string("R") : string("W")) + "A" + (isa<LoadInst>(J) ? string("R") : string("W"));
    return unique_instruction_id_I + " " + "NOM" + " " + depType + " " + unique_instruction_id_J + "|" +
           staticValueNameToMemRegIDMap[VNF->getVarName(I)]
               .first // use original variable name instead of LLVM IR SSA name
           + "(" + staticValueNameToMemRegIDMap[VNF->getVarName(I)].second + ")";
  }
}

void InstructionDG::dumpToDot(const string targetPath) {
  // Write the graph to a DOT file
  ofstream dotStream;
  dotStream.open(targetPath);

  dotStream << "digraph g {\n";
  // Create all nodes in DOT format
  for (auto instNode : getInstructionNodes()) {
    string label = "label=\"" + to_string(Graph::getInstructionNodeIndex(instNode)) + "\\n";
    Instruction *instr = instNode->getItem();
    if (isa<StoreInst>(instr)) {
      if (DebugLoc dl = instr->getDebugLoc())
        label += "write(";
      else
        label += "init(";
    } else if (isa<LoadInst>(instr))
      label += "read(";
    else
      label += "alloca(";
    label += VNF->getVarName(instr);
    label += ") ";

    if (DebugLoc dl = instr->getDebugLoc()) {
      label += to_string(dl.getLine());
      label += ", ";
      label += to_string(dl.getCol());
    } else if (isa<StoreInst>(instr)) {
      label += std::to_string(instr->getFunction()->getSubprogram()->getLine()) + "\n";
    }
    label += "\"";
    if (highlightedInstructionNodes.find(instr) != highlightedInstructionNodes.end()) {
      label += ",fillcolor=cyan,style=filled";
    }

    dotStream << "\t\"" << getInstructionNodeIndex(instNode) << "\" [" << label << "];\n";
  }
  dotStream << "\n\n";

  // Now print all outgoing edges and their labels
  for (auto e : getEdges()) {
    dotStream << "\t\"" << getInstructionNodeIndex(e->getSrc()) << "\" -> \"" << getInstructionNodeIndex(e->getDst())
              << "\";\n";
  }
  dotStream << "}";
  dotStream.close();
}
