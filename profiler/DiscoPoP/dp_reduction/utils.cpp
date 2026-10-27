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

#include <string>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::CallInst;
using llvm::cast;
using llvm::ConstantInt;
using llvm::DebugLoc;
using llvm::dyn_cast;
using llvm::Function;
using llvm::Instruction;
using llvm::IRBuilder;
using llvm::isa;
using llvm::MDNode;
using llvm::MDString;
using llvm::PointerType;
using llvm::StringRef;
using llvm::Type;
using llvm::Value;

// finds the previous use of 'val'
llvm::Instruction* dp_reduction::GetPrevUse(llvm::Instruction* instr, llvm::Value* val) {
  if (!instr) {
    return nullptr;
  }

  auto instr_users = val->users();
  bool instr_found = false;
  for (auto user : instr_users) {
    if (!llvm::isa<llvm::Instruction>(user)) {
      continue;
    }
    llvm::Instruction* usr_instr = llvm::cast<llvm::Instruction>(user);

    if (instr_found) {
      return usr_instr;
    }
    if (usr_instr == instr) {
      instr_found = true;
      continue;
    }
  }
  return llvm::dyn_cast<llvm::Instruction>(val);
}

int dp_reduction::GetOpOrder(char c) {
  if (c == '*' || c == '/') {
    return 5;
  }
  if (c == '+' || c == '-') {
    return 4;
  }
  if (c == '&') {
    return 3;
  }
  if (c == '^') {
    return 2;
  }
  if (c == '|') {
    return 1;
  }
  return 0;
}

Type* dp_reduction::PointsToStruct(PointerType* p_ty) {
  assert(p_ty);
  // (2025-10-30) Omitted check for struct type for llvm 19 compatibility
  Type* struct_type = p_ty;
  /*  if (PTy->getTypeID() == Type::PointerTyID) {
      while (structType->getTypeID() == Type::PointerTyID) {
        structType = cast<PointerType>(structType)->getPointerElementType();
      }
    }
  */
  return struct_type->getTypeID() == Type::StructTyID ? struct_type : nullptr;
}

std::string DiscoPoP::FindStructMemberNameStatic(MDNode* struct_node, unsigned idx, IRBuilder<>& builder) {
  assert(struct_node);
  assert(struct_node->getOperand(10));
  MDNode* member_list_nodes = cast<MDNode>(struct_node->getOperand(10));
  if (idx < member_list_nodes->getNumOperands()) {
    assert(member_list_nodes->getOperand(idx));
    MDNode* member = cast<MDNode>(member_list_nodes->getOperand(idx));
    if (member->getOperand(3)) {
      GetOrInsertVarNameStatic(dyn_cast<MDString>(member->getOperand(3))->getString().str(), builder);
      return dyn_cast<MDString>(member->getOperand(3))->getString().str();
    }
  }
  return "";
}

// returns the value that the GetElementPtrInst ultimately points to
llvm::Value* dp_reduction::PointsToVar(llvm::GetElementPtrInst* instr) {
  llvm::Value* points_to = nullptr;
  while (instr) {
    points_to = instr->getPointerOperand();
    instr = llvm::dyn_cast<llvm::GetElementPtrInst>(points_to);
  }
  return points_to;
}

// Encode the fileID and line number of BI as LID.
// This is needed to support multiple files in a project.
LID dp_reduction::GetLid(Instruction* bi, std::int32_t& /*file_id*/) {
  std::int32_t lno;

  const DebugLoc& location = bi->getDebugLoc();
  if (location) {
    lno = bi->getDebugLoc().getLine();
  } else {
    lno = 0;
  }

  if (lno == 0) {
    return 0;
  }
  LID const lid = lno;
  return lid;
}

bool dp_reduction::SanityCheck(BasicBlock* bb, int file_id) {
  LID lid;
  for (BasicBlock::iterator bi = bb->begin(), ei = bb->end(); bi != ei; ++bi) {
    lid = dp_reduction::GetLid(&*bi, file_id);
    if (lid > 0) {
      return true;
    }
  }
  return false;
}

// returns a char describing the opcode, e.g. '+' for Add or FAdd
// switches + and - if a negative constant is added or subtracted
// (mainly used to support -- as reduction operation, might be implemented as
// 'add -1')
char dp_reduction::GetCharForOpcode(llvm::Instruction* instr) {
  const unsigned opcode = instr->getOpcode();
  if (opcode == llvm::Instruction::Call) {
    // check for calls to relevant arithmetic intrinsic functions (fma, fmuladd)
    // full list of arithmetic intrinsics:
    // llvm.sqrt, llvm.fabs, llvm.powi, llvm.pow, llvm.exp, llvm.exp2, llvm.log, llvm.log2, llvm.log10, llvm.sin,
    // llvm.cos llvm.floor, llvm.ceil, llvm.trunc, llvm.rint, llvm.nearbyint, llvm.round, llvm.fma, llvm.fmuladd
    CallInst* call = dyn_cast<CallInst>(instr);
    Function* callee = call->getCalledFunction();
    if (callee && callee->getName().starts_with("llvm.")) {
      // check for relevant arithmentic intrinsics which allow a specific handling
      StringRef intrinsic_name = callee->getName();
      if (intrinsic_name.contains("fma") || intrinsic_name.contains("fmuladd")) {
        bool any_operand_is_negative_constant = false;
        if (instr->getNumOperands() >= 1) {
          for (unsigned i = 1; i < instr->getNumOperands(); ++i) {
            Value* rhs_value = instr->getOperand(i);
            if (isa<ConstantInt>(rhs_value)) {
              any_operand_is_negative_constant = cast<ConstantInt>(rhs_value)->isNegative();
            }
          }
        }

        if (any_operand_is_negative_constant) {
          return '-';
        }
        return '+';
      }
    }
  }

  if (opcode == llvm::Instruction::Add || opcode == llvm::Instruction::FAdd) {
    bool operand_is_negative_constant = false;
    if (instr->getNumOperands() >= 1) {
      Value* rhs_value = instr->getOperand(1);
      if (isa<ConstantInt>(rhs_value)) {
        operand_is_negative_constant = cast<ConstantInt>(rhs_value)->isNegative();
      }
    }

    if (operand_is_negative_constant) {
      return '-';
    }
    return '+';
  }
  if (opcode == llvm::Instruction::Sub || opcode == llvm::Instruction::FSub) {
    bool operand_is_negative_constant = false;
    if (instr->getNumOperands() >= 1) {
      Value* rhs_value = instr->getOperand(1);
      if (isa<ConstantInt>(rhs_value)) {
        operand_is_negative_constant = cast<ConstantInt>(rhs_value)->isNegative();
      }
    }

    if (operand_is_negative_constant) {
      return '+';
    }
    return '-';
  }
  if (opcode == llvm::Instruction::Mul || opcode == llvm::Instruction::FMul) {
    return '*';
  }
  if (opcode == llvm::Instruction::And) {
    return '&';
  }
  if (opcode == llvm::Instruction::Or) {
    return '|';
  }
  if (opcode == llvm::Instruction::Xor) {
    return '^';
  }
  return ' ';
}
