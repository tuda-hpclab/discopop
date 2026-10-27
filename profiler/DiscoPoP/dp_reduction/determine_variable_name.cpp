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
#include <string>

#include "DiscoPoP.hpp"

using llvm::cast;
using llvm::ConstantInt;
using llvm::GetElementPtrInst;
using llvm::GlobalVariable;
using llvm::Instruction;
using llvm::IRBuilder;
using llvm::isa;
using llvm::LoadInst;
using llvm::MDNode;
using llvm::PointerType;
using llvm::StoreInst;
using llvm::StructType;
using llvm::Type;
using llvm::Value;

std::string DiscoPoP::DpReductionDetermineVariableName(
    Instruction* i, std::map<std::string, std::string>* true_var_names_from_metadata_map) {
  assert(i && "Instruction cannot be NULL \n");
  const int index = isa<StoreInst>(i) ? 1 : 0;
  Value* operand = i->getOperand(index);

  IRBuilder<> builder(i);

  if (operand == nullptr) {
    std::string ret_val = GetOrInsertVarNameStatic("", builder);
    if (true_var_names_from_metadata_map->find(ret_val) == true_var_names_from_metadata_map->end()) {
      return ret_val;  // not found
    }
    return (*true_var_names_from_metadata_map)[ret_val];  // found
  }

  if (operand->hasName()) {
    //// we've found a global variable
    if (isa<GlobalVariable>(*operand)) {
      std::string ret_val = std::string(operand->getName());
      if (true_var_names_from_metadata_map->find(ret_val) == true_var_names_from_metadata_map->end()) {
        return ret_val;  // not found
      }
      return (*true_var_names_from_metadata_map)[ret_val];  // found
    }
    if (isa<GetElementPtrInst>(*operand)) {
      GetElementPtrInst* gep = cast<GetElementPtrInst>(operand);
      Value* ptr_operand = gep->getPointerOperand();
      PointerType* p_ty = cast<PointerType>(ptr_operand->getType());

      // we've found a struct/class
      // (2025-10-30) Simplified unpacking of structs for llvm 19 compatibility inside dp_reduction::pointsToStruct
      Type* struct_type = dp_reduction::PointsToStruct(p_ty);
      if (struct_type && gep->getNumOperands() > 2) {
        Value* const_value = gep->getOperand(2);
        if (const_value && isa<ConstantInt>(*const_value)) {
          ConstantInt* idx_ptr = cast<ConstantInt>(gep->getOperand(2));
          std::uint64_t member_idx = *(idx_ptr->getValue().getRawData());
          if (!(cast<StructType>(struct_type))->isLiteral()) {
            const std::string str_name(struct_type->getStructName().data());
            const std::map<std::string, MDNode*>::iterator it = structs_.find(str_name);
            if (it != structs_.end()) {
              const std::string ret = FindStructMemberNameStatic(it->second, member_idx, builder);
              if (ret.size() > 0) {
                std::string ret_val = ret;
                if (true_var_names_from_metadata_map->find(ret_val) == true_var_names_from_metadata_map->end()) {
                  return ret_val;  // not found
                }
                return (*true_var_names_from_metadata_map)[ret_val];  // found
              }
              std::string ret_val = GetOrInsertVarNameStatic("", builder);
              if (true_var_names_from_metadata_map->find(ret_val) == true_var_names_from_metadata_map->end()) {
                return ret_val;  // not found
              }
              return (*true_var_names_from_metadata_map)[ret_val];  // found
            }
          }
        }
      }

      // we've found an array
      // (25-10-30) Note: replaced for LLVM19 compatibility
      // OLD: if (PTy->getPointerElementType()->getTypeID() == Type::ArrayTyID && isa<GetElementPtrInst>(*ptrOperand)) {
      if (isa<GetElementPtrInst>(*ptr_operand)) {
        return DpReductionDetermineVariableName(cast<Instruction>(ptr_operand), true_var_names_from_metadata_map);
      }
      return DpReductionDetermineVariableName(static_cast<Instruction*>(gep), true_var_names_from_metadata_map);
    }
    std::string ret_val = std::string(operand->getName().data());
    if (true_var_names_from_metadata_map->find(ret_val) == true_var_names_from_metadata_map->end()) {
      return ret_val;  // not found
    }
    return (*true_var_names_from_metadata_map)[ret_val];  // found
  }

  if (isa<LoadInst>(*operand) || isa<StoreInst>(*operand)) {
    return DpReductionDetermineVariableName(cast<Instruction>(operand), true_var_names_from_metadata_map);
  }
  // if we cannot determine the name, then return *
  return "*";
}
