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

using llvm::AllocaInst;
using llvm::BasicBlock;
using llvm::CallBase;
using llvm::CallInst;
using llvm::cast;
using llvm::ConstantInt;
using llvm::DbgDeclareInst;
using llvm::DebugLoc;
using llvm::DINode;
using llvm::dyn_cast;
using llvm::errs;
using llvm::Function;
using llvm::InvokeInst;
using llvm::IRBuilder;
using llvm::isa;
using llvm::LLVMContext;
using llvm::LoadInst;
using llvm::MDNode;
using llvm::MDString;
using llvm::PointerType;
using llvm::ReturnInst;
using llvm::StoreInst;
using llvm::StringRef;
using llvm::Type;

/* metadata format in LLVM IR:
!5 = metadata !{
  i32,      ;; Tag (see below)  // DW_TAG_pointer_type:     0
  metadata, ;; Reference to context  // 1
  metadata, ;; Name (may be "" for anonymous types) // 2
  metadata, ;; Reference to file where defined (may be NULL) // 3
  i32,      ;; Line number where defined (may be 0) // 4
  i64,      ;; Size in bits // 5
  i64,      ;; Alignment in bits // 6
  i64,      ;; Offset in bits // 7
  i32,      ;; Flags to encode attributes, e.g. private // 8
  metadata, ;; Reference to type derived from     // 9   --> get operand at
index 9 metadata, ;; (optional) Name of the Objective C property associated with
            ;; Objective-C an ivar, or the type of which this
            ;; pointer-to-member is pointing to members of.
  metadata, ;; (optional) Name of the Objective C property getter selector.
  metadata, ;; (optional) Name of the Objective C property setter selector.
  i32       ;; (optional) Objective C property attributes.
}

A real case would be:
!2 = metadata !{
  i32 524307,        ;; Tag   // 0
  metadata !1,       ;; Context // 1
  metadata !"Color", ;; Name // 2
  metadata !1,       ;; Compile unit // 3
  i32 1,             ;; Line number // 4
  i64 96,            ;; Size in bits // 5
  i64 32,            ;; Align in bits // 6
  i64 0,             ;; Offset in bits // 7
  i32 0,             ;; Flags // 8
  null,              ;; Derived From // 9
  metadata !3,       ;; Elements // 10 --> list of elements
  i32 0              ;; Runtime Language
}
*/
// Recognizes every form of deallocation that a delete expression or a call to free can produce.
//
// The Itanium ABI mangles the global "operator delete" as _Zdl and "operator delete[]" as _Zda,
// followed by the encoded parameters, of which the first is always the pointer (Pv). Which overload
// clang picks depends on the language standard and on the type: a plain "delete p" became the sized
// _ZdlPvm in C++14, "delete[] p" is _ZdaPv, and over-aligned types add St11align_val_t. Matching the
// prefix therefore covers the whole family, including variants a future clang may add, instead of
// only the single spelling _ZdlPv.
static bool IsDeallocationFunction(StringRef fn) {
  return fn == "free" || fn.starts_with("_ZdlPv") || fn.starts_with("_ZdaPv");
}

// TODO: atomic variables
void DiscoPoP::RunOnBasicBlock(BasicBlock& bb) {
  for (BasicBlock::iterator bi = bb.begin(), e = bb.end(); bi != e; ++bi) {
    // assign unique instruction ids
    LLVMContext& ctx = bi->getContext();
    std::int32_t llvm_ir_instruction_id = unique_llvm_ir_instruction_id_++;
    MDNode* n = MDNode::get(ctx, MDString::get(ctx, "dp.md.instr.id:" + std::to_string(llvm_ir_instruction_id)));
    bi->setMetadata("dp.md.instr.id", n);
    // fill instructionID to lineID mapping file
    const DebugLoc& location = bi->getDebugLoc();
    std::uint32_t lno = 0;
    std::uint32_t colno = 0;
    if (location) {
      lno = location.getLine();
      colno = location.getCol();
    } else if (isa<AllocaInst>(bi) || isa<StoreInst>(bi)) {
      lno = bi->getFunction()->getSubprogram()->getLine();
    }
    if (lno != 0) {
      instruction_id_to_line_id_file << std::to_string(llvm_ir_instruction_id) << " " << std::to_string(file_id) << ":"
                                     << std::to_string(lno) << ":" << std::to_string(colno) << "\n";
    } else {
      instruction_id_to_line_id_file << std::to_string(llvm_ir_instruction_id) << " " << "*" << "\n";
    }

    if ([[maybe_unused]] DbgDeclareInst* di = dyn_cast<DbgDeclareInst>(bi)) {
      assert(di->getOperand(0));
#if false  // NOTE (25-10-30) DISABLED FOR LLVM 19 COMPATIBILITY REASONS
      if (AllocaInst *alloc = dyn_cast<AllocaInst>(DI->getOperand(0))) {
        Type *type = alloc->getAllocatedType();
        Type *structType = type;

        unsigned depth = 0;
        if (type->getTypeID() == Type::PointerTyID) {
          while (structType->getTypeID() == Type::PointerTyID) {
            structType = cast<PointerType>(structType)->getPointeeType();
            ++depth;
          }
        }
        if (structType->getTypeID() == Type::StructTyID) {
          assert(DI->getOperand(1));
          MDNode *varDesNode = DI->getVariable();
          assert(varDesNode->getOperand(5));
          MDNode *typeDesNode = cast<MDNode>(varDesNode->getOperand(5));
          MDNode *structNode = typeDesNode;
          if (type->getTypeID() == Type::PointerTyID) {
            MDNode *ptr = typeDesNode;
            for (unsigned i = 0; i < depth; ++i) {
              assert(ptr->getOperand(9));
              ptr = cast<MDNode>(ptr->getOperand(9));
            }
            structNode = ptr;
          }
          DINode *strDes = cast<DINode>(structNode);
          // DIDescriptor strDes(structNode);
          // handle the case when we have pointer to struct (or pointer to
          // pointer to struct ...)
          if (strDes->getTag() == dwarf::DW_TAG_pointer_type) {
            DINode *ptrDes = strDes;
            do {
              if (structNode->getNumOperands() < 10)
                break;
              assert(structNode->getOperand(9));
              structNode = cast<MDNode>(structNode->getOperand(9));
              ptrDes = cast<DINode>(structNode);
            } while (ptrDes->getTag() != dwarf::DW_TAG_structure_type);
          }

          if (strDes->getTag() == dwarf::DW_TAG_typedef) {
            assert(strDes->getOperand(9));
            structNode = cast<MDNode>(strDes->getOperand(9));
          }
          strDes = cast<DINode>(structNode);
          if (strDes->getTag() == dwarf::DW_TAG_structure_type) {
            std::string strName(structType->getStructName().data());
            if (Structs.find(strName) == Structs.end()) {
              processStructTypes(strName, structNode);
            }
          }
        }
      }
#endif
    } else if (isa<AllocaInst>(bi)) {
      // alloca instruction
      AllocaInst* ai = cast<AllocaInst>(bi);

      // if the option is set, check if the AllocaInst is static at the entry
      // block of a function and skip it's instrumentation. This leads to a
      // strong improvement of the profiling time if a lot of function calls are
      // used, but results in a worse accurracy. As the default, the accurate
      // profiling is used. Effectively, this check disables the instrumentation
      // of allocas which belong to function parameters.

      if (dp_memory_profiling_skip_function_arguments) {
        if (!ai->isStaticAlloca()) {
          // only instrument non-static alloca instructions
          InstrumentAlloca(ai);
        }
      } else {
        // instrument every alloca instruction
        InstrumentAlloca(ai);
      }
    } else if (isa<LoadInst>(bi)) {
      // load instruction
      InstrumentLoad(cast<LoadInst>(bi), llvm_ir_instruction_id);
    } else if (isa<StoreInst>(bi)) {
      // // store instruction
      InstrumentStore(cast<StoreInst>(bi), llvm_ir_instruction_id);
    } else if (IsaCallOrInvoke(&*bi)) {
      // call and invoke
      // resolves aliases, e.g. calls of constructors (see getCalledFunctionThroughAliases)
      Function* f = GetCalledFunctionThroughAliases(&*bi);

      // For ordinary function calls, F has a name.
      // However, sometimes the function being called
      // in IR is encapsulated by "bitcast()" due to
      // the way of compiling and linking. In this way,
      // getCalledFunction() method returns NULL.
      StringRef fn = "";
      if (f) {
        fn = f->getName();
        if (fn.find("__dp_") != std::string::npos) {  // avoid instrumentation calls
          continue;
        }
        if (fn.find("__clang_") != std::string::npos) {  // clang helper calls
          continue;
        }
        if (fn.str() == "pthread_exit") {
          // pthread_exit does not return to its caller.
          // Therefore, we insert DpFuncExit before pthread_exit
          IRBuilder<> irb_ret(&*bi);
          irb_ret.CreateCall(dp_func_exit_, {LidConstant(dputil::GetLid(&*bi, file_id)), ConstantInt::get(int32_, 0)});
          continue;
        }
        if ((fn.str() == "exit") || f->doesNotReturn()) {  // terminates without returning to main
          // exit() and quick_exit() run the handlers registered at program start, so the runtime is
          // shut down through .fini_array like on the ordinary path. The others -- abort(), _exit(),
          // a failed assertion -- bypass those, and the results collected so far would be lost
          // without shutting the runtime down here.
          if ((fn.str() != "exit") && (fn.str() != "quick_exit")) {
            InsertDpFinalize(&*bi);
          }
          continue;
        }
        if ((fn.str() == "_Znam") || (fn.str() == "_Znwm") || (fn.str() == "malloc")) {
          if (isa<CallInst>(bi)) {
            InstrumentNewOrMalloc(cast<CallInst>(bi));
          } else if (isa<InvokeInst>(bi)) {
            InstrumentNewOrMalloc(cast<InvokeInst>(bi));
          }
          continue;
        }
        if (fn.str() == "realloc") {
          if (isa<CallInst>(bi)) {
            InstrumentRealloc(cast<CallInst>(bi));
          } else if (isa<InvokeInst>(bi)) {
            InstrumentRealloc(cast<InvokeInst>(bi));
          }
          continue;
        }
        if (fn.str() == "calloc") {
          if (isa<CallInst>(bi)) {
            InstrumentCalloc(cast<CallInst>(bi));
          } else if (isa<InvokeInst>(bi)) {
            InstrumentCalloc(cast<InvokeInst>(bi));
          }
          continue;
        }

        if (fn.str() == "posix_memalign") {
          if (isa<CallInst>(bi)) {
            InstrumentPosixMemalign(cast<CallInst>(bi));
          } else if (isa<InvokeInst>(bi)) {
            InstrumentPosixMemalign(cast<InvokeInst>(bi));
          }
          continue;
        }
        if (IsDeallocationFunction(fn)) {
          InstrumentDeleteOrFree(cast<CallBase>(bi));
          continue;
        }
      }
      LID const lid = dputil::GetLid(&*bi, file_id);
      if (lid > 0) {  // calls on non-user code are not instrumented
        IRBuilder<> irb_call(&*bi);
        // the call site as a location, which the runtime reports for BGN func, and the instruction
        // id, on which it switches the callpath state. The state follows the call only if it enters
        // an instrumented function, see enter_function_for_callstate in the runtime library
        irb_call.CreateCall(dp_call_or_invoke_, {LidConstant(lid), ConstantInt::get(int32_, llvm_ir_instruction_id)});
        if (kDpDebug) {
          if (isa<CallInst>(bi)) {
            if (!(fn.str() == "")) {
              errs() << "calling " << fn << " on " << lid << "\n";
            } else {
              errs() << "calling unknown function on " << lid << "\n";
            }
          } else {
            if (!(fn.str() == "")) {
              errs() << "invoking " << fn << " on " << lid << "\n";
            } else {
              errs() << "invoking unknown function on " << lid << "\n";
            }
          }
        }
      }
    } else if (isa<ReturnInst>(bi)) {
      // return
      LID const lid = dputil::GetLid(&*bi, file_id);
      assert((lid > 0) && "Returning on LID = 0!");

      Function* parent = bb.getParent();
      assert(parent != NULL);
      StringRef fn = parent->getName();

      // main is not special here any more: the runtime is shut down from .fini_array, after the
      // destructors of the target's global objects have run, so main reports its exit like every
      // other function.
      IRBuilder<> irb_ret(&*bi);
      irb_ret.CreateCall(dp_func_exit_, {LidConstant(lid), ConstantInt::get(int32_, 0)});

      if (kDpDebug) {
        errs() << fn << " returning on " << lid << "\n";
      }
    }
  }
}
