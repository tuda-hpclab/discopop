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

using llvm::AllocaInst;
using llvm::cast;
using llvm::ConstantInt;
using llvm::DbgVariableRecord;
using llvm::DIGlobalVariable;
using llvm::filterDbgVars;
using llvm::GetElementPtrInst;
using llvm::GlobalVariable;
using llvm::Instruction;
using llvm::IRBuilder;
using llvm::isa;
using llvm::LoadInst;
using llvm::MDNode;
using llvm::PointerType;
using llvm::Region;
using llvm::StoreInst;
using llvm::StringRef;
using llvm::StructType;
using llvm::Type;
using llvm::Value;

std::string DiscoPoP::GetOrInsertVarNameStatic(std::string var_name, IRBuilder<>& builder) {
  Value* val_name = nullptr;
  // remove .addr if added. Replaced by the GEPRESULT_ tag
  if (var_name.find(".addr") != std::string::npos) {
    var_name.erase(var_name.find(".addr"), 5);
  }

  std::string v_name = var_name;
  const std::map<std::string, Value*>::iterator pair = var_names_.find(var_name);
  if (pair == var_names_.end()) {
    val_name = builder.CreateGlobalStringPtr(StringRef(var_name.c_str()), ".str");

    var_names_[var_name] = val_name;
  } else {
    v_name = pair->first;
  }

  return v_name;
}

Value* DiscoPoP::GetOrInsertVarNameDynamic(std::string var_name, IRBuilder<>& builder) {
  // remove .addr if added. Replaced by the GEPRESULT_ tag
  if (var_name.find(".addr") != std::string::npos) {
    var_name.erase(var_name.find(".addr"), 5);
  }

  // 26.08.2022 Lukas
  // update varName with original varName from Metadata
  if (true_var_names_from_metadata_map_.find(var_name) == true_var_names_from_metadata_map_.end()) {
    // not found, do nothing
  } else {
    // found, update varName
    var_name = true_var_names_from_metadata_map_[var_name];
  }

  Value* v_name = nullptr;
  const std::map<std::string, Value*>::iterator pair = var_names_.find(var_name);
  if (pair == var_names_.end()) {
    v_name = builder.CreateGlobalStringPtr(StringRef(var_name.c_str()), ".str");
    var_names_[var_name] = v_name;
  } else {
    v_name = pair->second;
  }
  return v_name;
}

std::string DiscoPoP::DetermineVariableNameStatic(Instruction* i,
                                                  bool& is_global_variable /*=defaultIsGlobalVariableValue*/,
                                                  bool disable_metadata_map, const std::string& prefix) {
  assert(i && "Instruction cannot be NULL \n");
  const int index = isa<StoreInst>(i) ? 1 : 0;
  Value* operand = i->getOperand(index);

  IRBuilder<> builder(i);

  if (operand == nullptr) {
    std::string ret_val = GetOrInsertVarNameStatic("", builder);
    if (true_var_names_from_metadata_map_.find(ret_val) == true_var_names_from_metadata_map_.end() ||
        disable_metadata_map) {
      return ret_val;  // not found
    }
    return true_var_names_from_metadata_map_[ret_val];  // found
  }

  if (operand->hasName()) {
    //// we've found a global variable
    if (isa<GlobalVariable>(*operand)) {
      // MOHAMMAD ADDED THIS FOR CHECKING
      is_global_variable = true;
      std::string ret_val = std::string(operand->getName());
      if (true_var_names_from_metadata_map_.find(ret_val) == true_var_names_from_metadata_map_.end() ||
          disable_metadata_map) {
        return ret_val;  // not found
      }
      return true_var_names_from_metadata_map_[ret_val];  // found
    }
    if (isa<GetElementPtrInst>(*operand)) {
      GetElementPtrInst* gep = cast<GetElementPtrInst>(operand);
      Value* ptr_operand = gep->getPointerOperand();
      PointerType* p_ty = cast<PointerType>(ptr_operand->getType());

      // we've found a struct/class
      Type* struct_type = PointsToStruct(p_ty);
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
                if (true_var_names_from_metadata_map_.find(ret_val) == true_var_names_from_metadata_map_.end() ||
                    disable_metadata_map) {
                  return ret_val;  // not found
                }
                return true_var_names_from_metadata_map_[ret_val];  // found
              }
              std::string ret_val = GetOrInsertVarNameStatic("", builder);
              if (true_var_names_from_metadata_map_.find(ret_val) == true_var_names_from_metadata_map_.end() ||
                  disable_metadata_map) {
                return ret_val;  // not found
              }
              return true_var_names_from_metadata_map_[ret_val];  // found

              // return ret;
            }
          }
        }
      }

      // we've found an array
      // NOTE (25-10-30) simplified for LLVM 19 compatibility
      // OLD: if (PTy->getPointerElementType()->getTypeID() == Type::ArrayTyID && isa<GetElementPtrInst>(*ptrOperand)) {
      if (isa<GetElementPtrInst>(*ptr_operand)) {
        return DetermineVariableNameStatic(cast<Instruction>(ptr_operand), is_global_variable, false, prefix);
      }
      return DetermineVariableNameStatic(static_cast<Instruction*>(gep), is_global_variable, false,
                                         "GEPRESULT_" + prefix);
    }
    std::string ret_val = std::string(operand->getName().data());
    if (true_var_names_from_metadata_map_.find(ret_val) == true_var_names_from_metadata_map_.end() ||
        disable_metadata_map) {
      return ret_val;  // not found
    }
    return true_var_names_from_metadata_map_[ret_val];  // found

    // return getOrInsertVarName(string(operand->getName().data()), builder);
  }

  if (isa<LoadInst>(*operand) || isa<StoreInst>(*operand)) {
    return DetermineVariableNameStatic(cast<Instruction>(operand), is_global_variable, false, prefix);
  }
  // if we cannot determine the name, then return *
  return "";  // getOrInsertVarName("*", builder);
}

Value* DiscoPoP::DetermineVariableNameDynamic(Instruction* const i, const std::string& prefix) {
  assert(i && "Instruction cannot be NULL \n");
  const int index = isa<StoreInst>(i) ? 1 : 0;
  Value* operand = i->getOperand(index);

  IRBuilder<> builder(i);

  if (operand == nullptr) {
    return GetOrInsertVarNameDynamic("*", builder);
  }

  if (operand->hasName()) {
    // we've found a global variable
    if (isa<GlobalVariable>(*operand)) {
      DIGlobalVariable* gv = FindDbgGlobalDeclare(cast<GlobalVariable>(operand));
      if (gv != nullptr) {
        return GetOrInsertVarNameDynamic(prefix + std::string(gv->getDisplayName().data()), builder);
      }
    }
    if (isa<GetElementPtrInst>(*operand)) {
      GetElementPtrInst* gep = cast<GetElementPtrInst>(operand);
      Value* ptr_operand = gep->getPointerOperand();
      PointerType* p_ty = cast<PointerType>(ptr_operand->getType());

      // we've found a struct/class
      Type* struct_type = PointsToStruct(p_ty);
      if (struct_type && gep->getNumOperands() > 2) {
        Value* const_value = gep->getOperand(2);
        if (const_value && isa<ConstantInt>(*const_value)) {
          ConstantInt* idx_ptr = cast<ConstantInt>(gep->getOperand(2));
          std::uint64_t member_idx = *(idx_ptr->getValue().getRawData());

          StructType* s_ty = cast<StructType>(struct_type);
          if (!s_ty->isLiteral()) {
            const std::string str_name(struct_type->getStructName().data());
            const std::map<std::string, MDNode*>::iterator it = structs_.find(str_name);
            if (it != structs_.end()) {
              Value* ret = FindStructMemberName(it->second, member_idx, builder);
              if (ret) {
                return ret;
              }
            }
          }
        }
      }

      // we've found an array
      // (2025-10-30) Simplified check for array type for llvm 19 compatibility
      // if (PTy->getPointerElementType()->getTypeID() == Type::ArrayTyID && isa<GetElementPtrInst>(*ptrOperand)) {
      if (isa<GetElementPtrInst>(*ptr_operand)) {
        return DetermineVariableNameDynamic(cast<Instruction>(ptr_operand), prefix);
      }
      return DetermineVariableNameDynamic(static_cast<Instruction*>(gep), "GEPRESULT_" + prefix);
    }
    return GetOrInsertVarNameDynamic(prefix + std::string(operand->getName().data()), builder);
  }

  if (isa<LoadInst>(*operand) || isa<StoreInst>(*operand)) {
    return DetermineVariableNameDynamic(cast<Instruction>(operand), prefix);
  }
  if (isa<AllocaInst>(i)) {
    return GetOrInsertVarNameDynamic(prefix + i->getName().str(), builder);
  }
  // if we cannot determine the name, then return *
  return GetOrInsertVarNameDynamic(prefix + "*", builder);
}

void DiscoPoP::GetTrueVarNamesFromMetadata(Region* top_region, Node* /*root*/,
                                           std::map<std::string, std::string>* true_var_names_from_metadata_map) {
  // check for deb_declare in Region
  // get IRVarName from first operand
  // get SRCVarName from second operand
  // update trueVarNamesFromMetadataMap
  for (auto bb : top_region->blocks()) {
    for (auto& inst : bb->instructionsWithoutDebug()) {
      auto dbg_record_range = inst.getDbgRecordRange();
      auto dbg_variable_range = filterDbgVars(dbg_record_range);
      for (DbgVariableRecord& dvr : dbg_variable_range) {
        const std::string ir_var_name = dvr.getValue()->getName().str();
        const std::string src_var_name = dvr.getVariable()->getName().str();
        // add to trueVarNamesFromMetadataMap
        // overwrite entry if already existing
        if (true_var_names_from_metadata_map->find(ir_var_name) == true_var_names_from_metadata_map->end()) {
          // not found
          true_var_names_from_metadata_map->insert(std::pair<std::string, std::string>(ir_var_name, src_var_name));
        } else {
          // found
          (*true_var_names_from_metadata_map)[ir_var_name] = src_var_name;
        }
      }
    }
  }
}
