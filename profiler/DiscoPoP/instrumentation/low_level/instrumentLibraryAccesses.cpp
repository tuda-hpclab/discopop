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

#include <vector>

#include "llvm/Analysis/ValueTracking.h"

#include "DiscoPoP.hpp"
#include "lid_constants.hpp"

using llvm::AllocaInst;
using llvm::BasicBlock;
using llvm::CallInst;
using llvm::ConstantInt;
using llvm::Function;
using llvm::FunctionCallee;
using llvm::Instruction;
using llvm::isa;
using llvm::LoadInst;
using llvm::PtrToIntInst;
using llvm::StoreInst;
using llvm::Value;

namespace {

// Whether the pointer certainly addresses a local of the function itself. Such memory is dead once the library call
// returns and never belongs to the project code that called it; the runtime drops the accesses to other stack memory
// of library frames (reached through a pointer) by its address.
// A parameter passed by value in memory (byval and the like) is a local as well, held in the caller's argument area,
// which is neither in a frame of the project nor below it.
bool AddressesOwnLocal(Value* pointer) {
  const Value* object = llvm::getUnderlyingObject(pointer);
  if (isa<AllocaInst>(object)) {
    return true;
  }
  if (const auto* argument = llvm::dyn_cast<llvm::Argument>(object)) {
    return argument->hasByValAttr() || argument->hasInAllocaAttr() || argument->hasPreallocatedAttr();
  }
  return false;
}

}  // namespace

// Library code (IsLibraryFunction) reports the accesses that may reach the memory of its callers, and nothing else: no
// instruction ids, no function entry or exit, no loops, no calls, no allocas. The runtime attributes every access to
// the call instruction of project code that entered the library (kLibraryAccessInstructionId), so a dependency inside
// a library call becomes one of that call, and a library loop runs within the call's iteration of the project loop.
void DiscoPoP::InstrumentLibraryAccesses(Function& f) {
  // nothing of the library has a file id; no helper may use the one of the function processed before
  file_id = 0;
  // Inlined into project code (the pass runs before the inliner), the locals of the library function would become
  // unregistered memory of the project frame, and its accesses would be attributed by the instruction ids of nothing.
  // An available_externally definition is never emitted: the call must still be inlined, or it links against a symbol
  // the shared library may not export (e.g. basic_string::_M_init_local_buf of the extern template in libstdc++ 13).
  // Its accesses then end up in the project function and are attributed to the last call of that frame. Its locals
  // become stack slots of the project frame that __dp_alloca never registered: should one escape into a library callee,
  // its accesses are kept under a library variable name (none of libstdc++ 13's always_inline functions does this).
  if (!f.hasAvailableExternallyLinkage()) {
    f.removeFnAttr(llvm::Attribute::AlwaysInline);
    f.addFnAttr(llvm::Attribute::NoInline);
  }
  std::vector<Instruction*> accesses;
  for (BasicBlock& bb : f) {
    for (Instruction& inst : bb) {
      if (auto* load = llvm::dyn_cast<LoadInst>(&inst)) {
        if (!AddressesOwnLocal(load->getPointerOperand())) {
          accesses.push_back(load);
        }
      } else if (auto* store = llvm::dyn_cast<StoreInst>(&inst)) {
        if (!AddressesOwnLocal(store->getPointerOperand())) {
          accesses.push_back(store);
        }
      }
    }
  }
  for (Instruction* access : accesses) {
    const bool is_store = isa<StoreInst>(access);
    Value* pointer = is_store ? llvm::cast<StoreInst>(access)->getPointerOperand()
                              : llvm::cast<LoadInst>(access)->getPointerOperand();
    std::vector<Value*> args;
    args.push_back(ConstantInt::get(int64_, kLibraryAccessInstructionId));
    args.push_back(PtrToIntInst::CreatePointerCast(pointer, int64_, "", access->getIterator()));
    args.push_back(DetermineVariableNameDynamic(access, ""));
#ifdef SKIP_DUP_INSTR
    // no duplicate tracking for library accesses
    args.push_back(ConstantInt::get(int64_, 0));
    args.push_back(ConstantInt::get(int64_, 0));
#endif
    CallInst::Create(is_store ? dp_write_ : dp_read_, args, "", access->getIterator());
  }
}
