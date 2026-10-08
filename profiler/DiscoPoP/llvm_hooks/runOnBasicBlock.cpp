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
static bool isDeallocationFunction(StringRef fn) {
  return fn == "free" || fn.starts_with("_ZdlPv") || fn.starts_with("_ZdaPv");
}

// TODO: atomic variables
void DiscoPoP::runOnBasicBlock(BasicBlock &BB) {
  for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
    // assign unique instruction ids
    LLVMContext& ctx = BI->getContext();
    int32_t llvm_ir_instruction_id = unique_llvm_ir_instruction_id++;
    MDNode* N = MDNode::get(ctx, MDString::get(ctx, "dp.md.instr.id:"+to_string(llvm_ir_instruction_id)));
    BI->setMetadata("dp.md.instr.id", N);
    // fill instructionID to lineID mapping file
    const DebugLoc &location = BI->getDebugLoc();
    uint32_t lno = 0;
    uint32_t colno = 0;
    if (location) {
      lno = location.getLine();
      colno = location.getCol();
    } else if (isa<AllocaInst>(BI) || isa<StoreInst>(BI)) {
      lno = BI->getFunction()->getSubprogram()->getLine();
    }
    if(lno != 0){
      *instructionID_to_lineID_file << to_string(llvm_ir_instruction_id) << " " << to_string(fileID) << ":" << to_string(lno) << ":" << to_string(colno) << "\n";
    } else{
      *instructionID_to_lineID_file << to_string(llvm_ir_instruction_id) << " " << "*" << "\n";
    }

    if (DbgDeclareInst *DI = dyn_cast<DbgDeclareInst>(BI)) {
      assert(DI->getOperand(0));
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
            string strName(structType->getStructName().data());
            if (Structs.find(strName) == Structs.end()) {
              processStructTypes(strName, structNode);
            }
          }
        }
      }
#endif
    }
    // alloca instruction
    else if (isa<AllocaInst>(BI)) {
      AllocaInst *AI = cast<AllocaInst>(BI);

      // if the option is set, check if the AllocaInst is static at the entry
      // block of a function and skip it's instrumentation. This leads to a
      // strong improvement of the profiling time if a lot of function calls are
      // used, but results in a worse accurracy. As the default, the accurate
      // profiling is used. Effectively, this check disables the instrumentation
      // of allocas which belong to function parameters.

      if (DP_MEMORY_PROFILING_SKIP_FUNCTION_ARGUMENTS) {
        if (!AI->isStaticAlloca()) {
          // only instrument non-static alloca instructions
          instrumentAlloca(AI);
        }
      } else {
        // instrument every alloca instruction
        instrumentAlloca(AI);
      }

    }
    // load instruction
    else if (isa<LoadInst>(BI)) {
      instrumentLoad(cast<LoadInst>(BI), llvm_ir_instruction_id);
    }
    // // store instruction
    else if (isa<StoreInst>(BI)) {
      instrumentStore(cast<StoreInst>(BI), llvm_ir_instruction_id);
    }
    // call and invoke
    else if (isaCallOrInvoke(&*BI)) {
      // resolves aliases, e.g. calls of constructors (see getCalledFunctionThroughAliases)
      Function *F = getCalledFunctionThroughAliases(&*BI);

      // For ordinary function calls, F has a name.
      // However, sometimes the function being called
      // in IR is encapsulated by "bitcast()" due to
      // the way of compiling and linking. In this way,
      // getCalledFunction() method returns NULL.
      StringRef fn = "";
      if (F) {
        fn = F->getName();
        if (fn.find("__dp_") != string::npos) // avoid instrumentation calls
        {
          continue;
        }
        if (fn.find("__clang_") != string::npos) // clang helper calls
        {
          continue;
        }
        if (fn.str() == "pthread_exit") {
          // pthread_exit does not return to its caller.
          // Therefore, we insert DpFuncExit before pthread_exit
          IRBuilder<> IRBRet(&*BI);
          IRBRet.CreateCall(DpFuncExit, {ConstantInt::get(Int32, getLID(&*BI, fileID)), ConstantInt::get(Int32, 0)});
          continue;
        }
        if ((fn.str() == "exit") || F->doesNotReturn()) // terminates without returning to main
        {
          // exit() and quick_exit() run the handlers registered at program start, so the runtime is
          // shut down through .fini_array like on the ordinary path. The others -- abort(), _exit(),
          // a failed assertion -- bypass those, and the results collected so far would be lost
          // without shutting the runtime down here.
          if ((fn.str() != "exit") && (fn.str() != "quick_exit")) {
            insertDpFinalize(&*BI);
          }
          continue;
        }
        if ((fn.str() == "_Znam") || (fn.str() == "_Znwm") || (fn.str() == "malloc")) {
          if (isa<CallInst>(BI)) {
            instrumentNewOrMalloc(cast<CallInst>(BI));
          } else if (isa<InvokeInst>(BI)) {
            instrumentNewOrMalloc(cast<InvokeInst>(BI));
          }
          continue;
        }
        if (fn.str() == "realloc") {
          if (isa<CallInst>(BI)) {
            instrumentRealloc(cast<CallInst>(BI));
          } else if (isa<InvokeInst>(BI)) {
            instrumentRealloc(cast<InvokeInst>(BI));
          }
          continue;
        }
        if (fn.str() == "calloc") {
          if (isa<CallInst>(BI)) {
            instrumentCalloc(cast<CallInst>(BI));
          } else if (isa<InvokeInst>(BI)) {
            instrumentCalloc(cast<InvokeInst>(BI));
          }
          continue;
        }

        if (fn.str() == "posix_memalign") {
          if (isa<CallInst>(BI)) {
            instrumentPosixMemalign(cast<CallInst>(BI));
          } else if (isa<InvokeInst>(BI)) {
            instrumentPosixMemalign(cast<InvokeInst>(BI));
          }
          continue;
        }
        if (isDeallocationFunction(fn)) {
          instrumentDeleteOrFree(cast<CallBase>(BI));
          continue;
        }
      }
      LID lid = getLID(&*BI, fileID);
      if (lid > 0) // calls on non-user code are not instrumented
      {
        IRBuilder<> IRBCall(&*BI);
        // the callpath state follows the call only if it enters an instrumented function, see
        // enter_function_for_callstate in the runtime library
        IRBCall.CreateCall(DpCallOrInvoke, {ConstantInt::get(Int32, llvm_ir_instruction_id)});
        if (DP_DEBUG) {
          if (isa<CallInst>(BI)) {
            if (!(fn.str() == ""))
              errs() << "calling " << fn << " on " << lid << "\n";
            else
              errs() << "calling unknown function on " << lid << "\n";
          } else {
            if (!(fn.str() == ""))
              errs() << "invoking " << fn << " on " << lid << "\n";
            else
              errs() << "invoking unknown function on " << lid << "\n";
          }
        }
      }
    }
    // return
    else if (isa<ReturnInst>(BI)) {
      LID lid = getLID(&*BI, fileID);
      assert((lid > 0) && "Returning on LID = 0!");

      Function *parent = BB.getParent();
      assert(parent != NULL);
      StringRef fn = parent->getName();

      // main is not special here any more: the runtime is shut down from .fini_array, after the
      // destructors of the target's global objects have run, so main reports its exit like every
      // other function.
      IRBuilder<> IRBRet(&*BI);
      IRBRet.CreateCall(DpFuncExit, {ConstantInt::get(Int32, lid), ConstantInt::get(Int32, 0)});

      if (DP_DEBUG) {
        errs() << fn << " returning on " << lid << "\n";
      }
    }
  }
}
