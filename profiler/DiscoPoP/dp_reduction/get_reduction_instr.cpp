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

// Retrieves the reduction operation for the operand that is stored by the
// 'store_instr' (if such a reduction operation exists).
// The parameter 'load_instr' will point to the load instruction that actually
// loads the value (if such a load instruction exists).
llvm::Instruction *DiscoPoP::dp_reduction_get_reduction_instr(llvm::Instruction *store_instr,
                                                              llvm::Instruction **load_instr) {
  // find the reduction operation for the source operand of the 'store_instr'
  llvm::Instruction *reduction_instr = dp_reduction_find_reduction_instr(store_instr->getOperand(0));
  if (!reduction_instr) {
    return nullptr;
  }
  // Now find the destination address of the store instruction.
  // After that, search the load instruction that loads this value and store a
  // pointer to it in 'load_instr'.
  llvm::Value *store_dst = dp_reduction_get_var_rec(store_instr->getOperand(1));
  if (store_dst) {
    std::vector<char> reduction_operations;
    *load_instr = dp_reduction_get_load_instr(store_dst, reduction_instr, reduction_operations);
    // { *, / } > { +, - } > { & } > { ^ } > { | }
    if (reduction_operations.size() > 1) {
      int order = dp_reduction_get_op_order(reduction_operations[0]);
      for (size_t i = 1; i != reduction_operations.size(); ++i) {
        int order_i = dp_reduction_get_op_order(reduction_operations[i]);
        if (order_i > order) {
          *load_instr = nullptr;
          return nullptr;
        }
      }
    }
    if (*load_instr) {
      return reduction_instr;
    }
  }

  return nullptr;
}
