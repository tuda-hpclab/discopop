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

llvm::Value *DiscoPoP::dp_reduction_get_var_rec(llvm::Value *val) {
  if (!val)
    return nullptr;

  if (llvm::isa<llvm::AllocaInst>(val) || llvm::isa<llvm::GlobalVariable>(val)) {
    return val;
  }
  if (llvm::isa<llvm::GetElementPtrInst>(val)) {
    llvm::GetElementPtrInst *elem_ptr_instr = llvm::cast<llvm::GetElementPtrInst>(val);

    // struct member reductions are not supported by OpenMP
    llvm::Value *points_to = dp_reduction_points_to_var(elem_ptr_instr);
    llvm::AllocaInst *a_instr = llvm::dyn_cast<llvm::AllocaInst>(points_to);
    llvm::Type *type = (a_instr) ? a_instr->getAllocatedType() : points_to->getType();
    if (type->isStructTy()) {
      return nullptr;
    }

    return dp_reduction_get_var_rec(elem_ptr_instr->getPointerOperand());
  }
  if (llvm::isa<llvm::LoadInst>(val)) {
    llvm::LoadInst *load_instr = llvm::cast<llvm::LoadInst>(val);
    return dp_reduction_get_var_rec(load_instr->getOperand(0));
  }

  return nullptr;
}

// Get the value that is stored or loaded by a store / load instruction.
llvm::Value *DiscoPoP::dp_reduction_get_var(llvm::Instruction *instr) {
  unsigned index = (llvm::isa<llvm::LoadInst>(instr)) ? 0 : 1;
  return dp_reduction_get_var_rec(instr->getOperand(index));
}
