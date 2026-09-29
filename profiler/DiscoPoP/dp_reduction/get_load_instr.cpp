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

// Finds the load instruction that actually loads the value from the address
// 'load_val'.
llvm::Instruction *DiscoPoP::dp_reduction_get_load_instr(llvm::Value *load_val, llvm::Instruction *cur_instr,
                                                         std::vector<char> &reduction_operations) {
  if (!load_val || !cur_instr)
    return nullptr;
  if (llvm::isa<llvm::LoadInst>(cur_instr)) {
    // Does the current instruction already load the value from the correct
    // address? If that is the case, return it.
    llvm::Value *val = cur_instr->getOperand(0);
    if (val == load_val)
      return cur_instr;

    // The current instruction does not load the value from the address of
    // 'load_val'. But it might load the value from a variable where 'load_val'
    // is stored in, so find the previous use of the source operand.
    llvm::Instruction *prev_use = dp_reduction_get_prev_use(cur_instr, val);
    if (prev_use) {
      if (llvm::isa<llvm::StoreInst>(prev_use)) {
        return dp_reduction_get_load_instr(load_val, prev_use, reduction_operations);
      } else if (llvm::isa<llvm::GetElementPtrInst>(prev_use)) {
        llvm::GetElementPtrInst *ptr_instr = llvm::cast<llvm::GetElementPtrInst>(prev_use);
        llvm::Value *points_to = dp_reduction_points_to_var(ptr_instr);
        if (points_to == load_val) {
          return cur_instr;
        } else {
          bool found = static_cast<bool>(dp_reduction_get_load_instr(
              load_val, llvm::dyn_cast<llvm::Instruction>(points_to), reduction_operations));
          return (found) ? cur_instr : nullptr;
        }
      } else {
        bool found = static_cast<bool>(dp_reduction_get_load_instr(load_val, prev_use, reduction_operations));
        return (found) ? cur_instr : nullptr;
      }
    } else {
      return nullptr;
    }
  }

  char c = dp_reduction_get_char_for_opcode(cur_instr);
  if (c != ' ') {
    reduction_operations.push_back(c);
  }

  // The current instruction is not a load instruction. Follow the operands
  // of the current instruction recursively until the desired load instruction
  // is reached.
  llvm::Instruction *result = nullptr;
  for (unsigned int i = 0; i != cur_instr->getNumOperands(); ++i) {
    llvm::Value *operand = cur_instr->getOperand(i);
    if (llvm::isa<llvm::Instruction>(operand)) {
      result = dp_reduction_get_load_instr(load_val, llvm::cast<llvm::Instruction>(operand), reduction_operations);
      if (result) {
        break;
      }
    }
  }

  if (!result && c != ' ') {
    reduction_operations.pop_back();
  }

  return result;
}
