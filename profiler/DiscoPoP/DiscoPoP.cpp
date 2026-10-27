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

// #define SKIP_DUP_INSTR 1

#include "DiscoPoP.hpp"

#include <string>

// after the includes: LLVM headers define their own DEBUG_TYPE
#undef DEBUG_TYPE
#define DEBUG_TYPE "dpop"
// #define DEBUG_TYPE "dp-omissions"

using llvm::cast;
using llvm::DINamespace;
using llvm::DINode;
using llvm::DIType;
using llvm::dyn_cast;
using llvm::errs;
using llvm::IntegerType;
using llvm::MDNode;
using llvm::MDString;
using llvm::PointerType;
using llvm::Type;

// Initializations
void DiscoPoP::SetupDataTypes() {
  void_type_ = Type::getVoidTy(*this_module_context_);
  int32_ = IntegerType::getInt32Ty(*this_module_context_);
  int64_ = IntegerType::getInt64Ty(*this_module_context_);
  char_ptr_ = PointerType::getUnqual(Type::getInt8Ty(*this_module_context_));
}

void DiscoPoP::SetupCallbacks() {
  /* function name
   * return value type
   * arg types
   *
   * the callbacks are extern "C" functions of the runtime library, whose signatures are in
   * rtlib/injected_functions/<callback>.hpp: a location (LID) or address is a 64 bit integer there, so it is
   * declared as Int64 here. A narrower declaration would leave the upper half of the argument
   * register unspecified. test/instrumentation/test_callback_signatures.py compares both.
   */

  dp_finalize_ = this_module_->getOrInsertFunction("__dp_finalize", void_type_, int64_);

  dp_read_ = this_module_->getOrInsertFunction("__dp_read", void_type_,
#ifdef SKIP_DUP_INSTR
                                               int64_, int64_, char_ptr_, int64_, int64_);
#else
                                               int64_, int64_, char_ptr_);
#endif

  dp_write_ = this_module_->getOrInsertFunction("__dp_write", void_type_,
#ifdef SKIP_DUP_INSTR
                                                int64_, int64_, char_ptr_, int64_, int64_);
#else
                                                int64_, int64_, char_ptr_);
#endif

  dp_alloca_ = this_module_->getOrInsertFunction("__dp_alloca", void_type_,

                                                 int64_, char_ptr_, int64_, int64_, int64_, int64_);

  dp_new_ = this_module_->getOrInsertFunction("__dp_new", void_type_, int64_, int64_, int64_, int64_);

  dp_delete_ = this_module_->getOrInsertFunction("__dp_delete", void_type_, int64_, int64_);

  dp_call_or_invoke_ = this_module_->getOrInsertFunction("__dp_call", void_type_, int64_, int32_);

  dp_func_entry_ = this_module_->getOrInsertFunction("__dp_func_entry", void_type_, int64_, int32_, int32_);

  dp_func_exit_ = this_module_->getOrInsertFunction("__dp_func_exit", void_type_, int64_, int32_);

  dp_loop_entry_ = this_module_->getOrInsertFunction("__dp_loop_entry", void_type_, int64_, int32_, int32_);

  dp_loop_exit_ = this_module_->getOrInsertFunction("__dp_loop_exit", void_type_, int64_, int32_, int32_);

  dp_taken_branch_counter_incr_ =
      this_module_->getOrInsertFunction("__dp_incr_taken_branch_counter", void_type_, char_ptr_, int32_, int32_);
}

// DPReduction end

#if false  // NOTE (25-10-30) DISABLED FOR LLVM 19 COMPATIBILITY REASONS
void DiscoPoP::processStructTypes(std::string const &fullStructName, MDNode *structNode) {
  assert(structNode && "structNode cannot be NULL");
  DIType *strDes = cast<DIType>(structNode);
  assert(strDes->getTag() == dwarf::DW_TAG_structure_type);
  // sometimes it's impossible to get the list of struct members (e.g badref)
  if (structNode->getNumOperands() <= 10 || structNode->getOperand(10) == NULL) {
    errs() << "cannot process member list of this struct: \n";
    structNode->dump();
    return;
  }
  Structs[fullStructName] = structNode;

  MDNode *memberListNodes = cast<MDNode>(structNode->getOperand(10));
  for (unsigned i = 0; i < memberListNodes->getNumOperands(); ++i) {
    assert(memberListNodes->getOperand(i));
    MDNode *member = cast<MDNode>(memberListNodes->getOperand(i));
    DINode *memberDes = cast<DINode>(member);
    // DIDescriptor memberDes(member);
    if (memberDes->getTag() == dwarf::DW_TAG_member) {
      assert(member->getOperand(9));
      MDNode *memberType = cast<MDNode>(member->getOperand(9));
      DIType *memberTypeDes = cast<DIType>(memberType);
      // DIType memberTypeDes(memberType);
      if (memberTypeDes->getTag() == dwarf::DW_TAG_structure_type) {
        std::string fullName = "";
        // try to get namespace
        if (memberType->getNumOperands() > 2 && structNode->getOperand(2) != NULL) {
          MDNode *namespaceNode = cast<MDNode>(structNode->getOperand(2));
          DINamespace *dins = cast<DINamespace>(namespaceNode);
          // DINameSpace dins(namespaceNode);
          fullName = "struct." + std::string(dins->getName().data()) + "::";
        }
        // fullName += string(memberType->getOperand(3)->getName().data());
        fullName += (dyn_cast<MDString>(memberType->getOperand(3)))->getString();

        if (Structs.find(fullName) == Structs.end())
          processStructTypes(fullName, memberType);
      }
    }
  }
}
#endif
