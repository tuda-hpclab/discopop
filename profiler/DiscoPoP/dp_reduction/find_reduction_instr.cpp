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

// returns the reduction instruction where 'val' is the operand if it can find
// such an operation
llvm::Instruction *DiscoPoP::dp_reduction_find_reduction_instr(llvm::Value *val) {
  if (!val || !llvm::isa<llvm::Instruction>(val)) {
    return nullptr;
  }
  llvm::Instruction *instr = llvm::cast<llvm::Instruction>(val);
  unsigned opcode = instr->getOpcode();
  char c = dp_reduction_get_char_for_opcode(instr);
  if (c != ' ') {
    return instr;
  } else if (opcode == llvm::Instruction::Load) {
    llvm::Instruction *prev_use = dp_reduction_get_prev_use(instr, instr->getOperand(0));
    return dp_reduction_find_reduction_instr(prev_use);
  } else if (opcode == llvm::Instruction::Store) {
    return dp_reduction_find_reduction_instr(instr->getOperand(0));
  }
  // enter recursion if the instruction has only a single operand to accomodate
  // for type conversions etc.
  if (instr->getNumOperands() == 1) {
    // unpack instruction
    return dp_reduction_find_reduction_instr(instr->getOperand(0));
  }
  // no reduction instruction found
  return nullptr;
}
