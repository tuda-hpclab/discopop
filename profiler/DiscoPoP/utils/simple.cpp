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

#include <map>
#include <set>
#include <string>
#include <utility>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::CallGraph;
using llvm::CallInst;
using llvm::cast;
using llvm::Constant;
using llvm::DbgDeclareInst;
using llvm::DebugLoc;
using llvm::DICompileUnit;
using llvm::DIGlobalVariable;
using llvm::dyn_cast;
using llvm::errs;
using llvm::Function;
using llvm::GlobalVariable;
using llvm::Instruction;
using llvm::InvokeInst;
using llvm::IRBuilder;
using llvm::isa;
using llvm::Loop;
using llvm::LoopInfo;
using llvm::MDNode;
using llvm::MDString;
using llvm::NamedMDNode;
using llvm::PHINode;
using llvm::PointerType;
using llvm::Region;
using llvm::ReturnInst;
using llvm::Type;
using llvm::Value;

Type* DiscoPoP::PointsToStruct(PointerType* p_ty) {
  assert(p_ty);
  Type* struct_type = p_ty;
  // (2025-10-30) Simplified for llvm 19 compatibility
  /*
  if (PTy->getTypeID() == Type::PointerTyID) {
    while (structType->getTypeID() == Type::PointerTyID) {
      structType = cast<PointerType>(structType)->getElementType();
    }
  }
  */
  return struct_type->getTypeID() == Type::StructTyID ? struct_type : nullptr;
}

Value* DiscoPoP::FindStructMemberName(MDNode* struct_node, unsigned idx, IRBuilder<>& builder) {
  assert(struct_node);
  assert(struct_node->getOperand(10));
  MDNode* member_list_nodes = cast<MDNode>(struct_node->getOperand(10));
  if (idx < member_list_nodes->getNumOperands()) {
    assert(member_list_nodes->getOperand(idx));
    MDNode* member = cast<MDNode>(member_list_nodes->getOperand(idx));
    if (member->getOperand(3)) {
      return GetOrInsertVarNameDynamic(dyn_cast<MDString>(member->getOperand(3))->getString().str(), builder);
    }
  }
  return nullptr;
}

DIGlobalVariable* DiscoPoP::FindDbgGlobalDeclare(GlobalVariable* v) {
  assert(v && "Global variable cannot be null");
  for (std::set<DIGlobalVariable*>::iterator it = global_vars_.begin(); it != global_vars_.end(); ++it) {
    if ((*it)->getDisplayName() == v->getName()) {
      return *it;
    }
  }
  return nullptr;
}

void DiscoPoP::CollectDebugInfo() {
  if (NamedMDNode* cu_nodes = this_module_->getNamedMetadata("llvm.dbg.cu")) {
    for (unsigned i = 0, e = cu_nodes->getNumOperands(); i != e; ++i) {
      DICompileUnit* cu = cast<DICompileUnit>(cu_nodes->getOperand(i));
      auto gvs = cu->getGlobalVariables();
      for (unsigned i = 0, e = gvs.size(); i < e; ++i) {
        DIGlobalVariable* dig = gvs[i]->getVariable();
        if (dig) {
          global_vars_.insert(dig);
        }
      }
    }
  }
}

bool DiscoPoP::IsaCallOrInvoke(Instruction* bi) const {
  return (bi != nullptr) && ((isa<CallInst>(bi) && (!isa<DbgDeclareInst>(bi))) || isa<InvokeInst>(bi));
}

bool DiscoPoP::SanityCheck(BasicBlock* bb) {
  LID lid;
  for (BasicBlock::iterator bi = bb->begin(), ei = bb->end(); bi != ei; ++bi) {
    lid = dputil::GetLid(&*bi, file_id);
    if (lid > 0) {
      return true;
    }
  }
  if (kDpVerbose) {
    errs() << "WARNING: basic block " << bb << " doesn't contain valid LID.\n";
  }
  return false;
}

// Returns the LID to report when the loop L is left through the exit block BB: the LID of the
// first instruction of BB carrying one. Clang emits the branch that leaves an if/else arm
// without a debug location, so the exit block of a loop that ends an arm (e.g. a loop in an
// `else` inside another loop) may contain no valid LID at all. Then the LID of the first
// block along BB's chain of unique successors that has one is used, i.e. the code executed
// right after the loop, as for an ordinary exit block. The chain ends before the header or the
// latch (e.g. `for.inc`) of an enclosing loop: their LIDs belong to the enclosing loop's
// statement, which starts before L. Without a LID up to there, the end location of L is used.
LID DiscoPoP::GetLoopExitLid(BasicBlock* bb, Loop* l) {
  std::set<BasicBlock*> visited;
  while (bb != nullptr && visited.insert(bb).second) {
    bool belongs_to_enclosing_loop_statement = false;
    for (Loop* p = (l != nullptr ? l->getParentLoop() : nullptr); p != nullptr; p = p->getParentLoop()) {
      if (bb == p->getHeader() || p->isLoopLatch(bb)) {
        belongs_to_enclosing_loop_statement = true;
        break;
      }
    }
    if (belongs_to_enclosing_loop_statement) {
      break;
    }
    for (BasicBlock::iterator bi = bb->begin(), ei = bb->end(); bi != ei; ++bi) {
      LID const lid = dputil::GetLid(&*bi, file_id);
      if (lid > 0 && !isa<PHINode>(bi)) {
        return lid;
      }
    }
    bb = bb->getUniqueSuccessor();
  }
  if (l != nullptr && file_id > 0) {
    DebugLoc end_loc = l->getLocRange().getEnd();
    if (end_loc && end_loc.getLine() > 0) {
      return dputil::EncodeLid(file_id, end_loc.getLine());
    }
  }
  return 0;
}

bool dp_reduction::CheckValueUsage(llvm::Value* parent_value, llvm::Value* searched_value) {
  // Return true, if searchedValue is used within the computation of parentValue
  if (parent_value == searched_value) {
    return true;
  }

  // check operands recursively, if parentValue is not a constant yet
  if (isa<Constant>(parent_value)) {
    return false;
  }
  // if parentValue is not an Instruction, the value can not be used, thus
  // return false
  if (!isa<Instruction>(parent_value)) {
    errs() << "parentValue not an Instruction.\n";
    return false;
  }

  const llvm::Instruction* parent_instruction = cast<Instruction>(parent_value);
  for (unsigned int idx = 0; idx < parent_instruction->getNumOperands(); idx++) {
    if (CheckValueUsage(parent_instruction->getOperand(idx), searched_value)) {
      return true;
    }
  }

  return false;
}

bool dp_reduction::InlinedFunction(Function* f) {
  for (Function::iterator fi = f->begin(), fe = f->end(); fi != fe; ++fi) {
    for (BasicBlock::iterator bi = fi->begin(), e = fi->end(); bi != e; ++bi) {
      if (DbgDeclareInst* di = dyn_cast<DbgDeclareInst>(bi)) {
        if (di->getDebugLoc()->getInlinedAt()) {
          return true;
        }
      }
    }
  }
  return false;
}

bool DiscoPoP::IsRecursive(Function& f, CallGraph& cg) {
  auto call_node = cg[&f];
  for (unsigned i = 0; i < call_node->size(); i++) {
    if ((*call_node)[i]->getFunction() == &f) {
      return true;
    }
  }
  return false;
}

void DiscoPoP::FillStartEndLineNumbers(Node* root, LoopInfo& li, std::map<Loop*, std::string>& loop_to_pet_node_id) {
  if (root->type != NodeTypes::kCu) {
    LID start = -1, end = -1;

    if (root->type == NodeTypes::kLoop) {
      for (auto i : root->children_nodes) {
        if (i->type == NodeTypes::kCu) {
          Loop* loop = li.getLoopFor(i->bb);
          DebugLoc dl = loop->getStartLoc();
          LID lid = 0;
          lid = dputil::EncodeLid(file_id, dl->getLine());
          loop_start_lines_[root->id] = dputil::DecodeLid(lid);
          loop_to_pet_node_id[loop] = root->id;
          break;
        }
      }
    }
    FindStartEndLineNumbers(root, start, end);

    root->start_line = start;
    root->end_line = end;
  }

  for (auto i : root->children_nodes) {
    FillStartEndLineNumbers(i, li, loop_to_pet_node_id);
  }
}

void DiscoPoP::FindStartEndLineNumbers(Node* root, LID& start, LID& end) {
  if (root->type == NodeTypes::kCu) {
    if (start == -1 || start > root->start_line) {
      start = root->start_line;
    }

    if (end < root->end_line) {
      end = root->end_line;
    }
  }

  for (auto i : root->children_nodes) {
    FindStartEndLineNumbers(i, start, end);
  }
}

void DiscoPoP::GetFunctionReturnLines(Region* top_region, Node* root) {
  LID lid = 0;
  for (Region::block_iterator bb = top_region->block_begin(); bb != top_region->block_end(); ++bb) {
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      if (isa<ReturnInst>(instruction)) {
        lid = dputil::GetLid(&*instruction, file_id);
        if (lid > 0) {
          root->return_lines.insert(lid);
        }
      }
    }
  }
}

std::int32_t DiscoPoP::GetOrRegisterLoopId(llvm::Loop* l) {
  // Check if loop is already registered
  std::int32_t tmp_loop_id;
  auto pos = loop_to_id.find(l);
  if (pos != loop_to_id.end()) {
    // L found. Return loop id
    tmp_loop_id = pos->second;
  } else {
    // L not found. register loop id
    tmp_loop_id = loop_id_;
    loop_to_id.insert(std::make_pair(l, tmp_loop_id));
    loop_id_++;
  }
  return tmp_loop_id;
}
