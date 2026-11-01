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

#include <iostream>
#include <string>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::CallInst;
using llvm::cast;
using llvm::ConstantInt;
using llvm::dyn_cast;
using llvm::Function;
using llvm::FunctionCallee;
using llvm::Instruction;
using llvm::IRBuilder;
using llvm::isa;
using llvm::LLVMContext;
using llvm::MDNode;
using llvm::MDString;
using llvm::Module;
using llvm::Type;

void DiscoPoP::AssignInstructionIdsToDpReductionFunctions(Module& m) {
  for (Function& f : m) {
    for (BasicBlock& bb : f) {
      for (BasicBlock::iterator bi = bb.begin(), e = bb.end(); bi != e; ++bi) {
        auto instruction = &*bi;
        if (isa<CallInst>(instruction)) {
          auto ci = cast<CallInst>(bi);
          Function* f = ci->getCalledFunction();
          if (f) {
            auto fn = f->getName();
            if (fn.find("__dp_loop_incr") != std::string::npos) {
              // assign missing unique instruction id
              LLVMContext& ctx = bi->getContext();
              std::int32_t llvm_ir_instruction_id = GetNextInstructionId();
              MDNode* n =
                  MDNode::get(ctx, MDString::get(ctx, "dp.md.instr.id:" + std::to_string(llvm_ir_instruction_id)));
              bi->setMetadata("dp.md.instr.id", n);
              // fill instructionID to lineID mapping file
              instruction_id_to_line_id_file << std::to_string(llvm_ir_instruction_id) << " "
                                             << dputil::DecodeLid(dputil::GetLid(&*bi, file_id)) << "\n";
            }
          }
        }
      }
    }
  }
}

void DiscoPoP::UpdateArgumentInstructionIds(Module& m) {
  std::cout << "Updating argument instruction ids...\n";
  for (Function& f : m) {
    for (BasicBlock& bb : f) {
      for (BasicBlock::iterator bi = bb.begin(), e = bb.end(); bi != e; ++bi) {
        auto instruction = &*bi;
        if (isa<CallInst>(instruction)) {
          auto ci = cast<CallInst>(bi);
          Function* f = ci->getCalledFunction();
          if (f) {
            auto fn = f->getName();
            if (fn.find("__dp_loop_entry") != std::string::npos) {
              // Get InstructionID of callinstruction
              MDNode* md = bi->getMetadata("dp.md.instr.id");
              std::int32_t call_instruction_id = 0;
              if (md) {
                // Metadata exists
                std::string call_instruction_id_str = cast<MDString>(md->getOperand(0))->getString().str();
                call_instruction_id_str.erase(0, 15);
                call_instruction_id = std::stoi(call_instruction_id_str);
              }
              // update the function argument
              if (call_instruction_id != 0) {
                ci->setArgOperand(2, ConstantInt::get(int32_, call_instruction_id));
              }
            }
            if (fn.find("__dp_loop_incr") != std::string::npos) {
              // Get InstructionID of callinstruction
              MDNode* md = bi->getMetadata("dp.md.instr.id");
              std::int32_t call_instruction_id = 0;
              if (md) {
                // Metadata exists
                std::string call_instruction_id_str = cast<MDString>(md->getOperand(0))->getString().str();
                call_instruction_id_str.erase(0, 15);
                call_instruction_id = std::stoi(call_instruction_id_str);
              }
              // update the function argument
              if (call_instruction_id != 0) {
                ci->setArgOperand(1, ConstantInt::get(int32_, call_instruction_id));
              }
            }
            if (fn == "__dp_func_entry") {
              // the instruction id of the entry call identifies the function at runtime, see
              // callpath_function_entries.txt
              std::int32_t call_instruction_id = GetDpInstructionId(&*bi);
              if (call_instruction_id != 0) {
                ci->setArgOperand(2, ConstantInt::get(int32_, call_instruction_id));
              }
            }
            if (fn.find("__dp_loop_exit") != std::string::npos) {
              // Get InstructionID of callinstruction
              MDNode* md = bi->getMetadata("dp.md.instr.id");
              std::int32_t call_instruction_id = 0;
              if (md) {
                // Metadata exists
                std::string call_instruction_id_str = cast<MDString>(md->getOperand(0))->getString().str();
                call_instruction_id_str.erase(0, 15);
                call_instruction_id = std::stoi(call_instruction_id_str);
              }
              // update the function argument
              if (call_instruction_id != 0) {
                ci->setArgOperand(2, ConstantInt::get(int32_, call_instruction_id));
              }
            }
          }
        }
      }
    }
  }
}

// Inserts a call of __dp_landing_pad(<function entry id>) at the start of every landing pad of an
// instrumented function. An exception leaves functions without their __dp_func_exit calls; the
// runtime library discards their callpath states when the exception reaches a landing pad.
// Requires the function entry ids assigned by update_argument_instruction_ids.
void DiscoPoP::InstrumentLandingPads(Module& m) {
  FunctionCallee dp_landing_pad = m.getOrInsertFunction("__dp_landing_pad", Type::getVoidTy(m.getContext()), int32_);
  for (Function& f : m) {
    if (f.isDeclaration()) {
      continue;
    }
    // the function entry id is the last argument of the function's __dp_func_entry call
    ConstantInt* function_entry_id = nullptr;
    for (Instruction& i : f.getEntryBlock()) {
      auto ci = dyn_cast<CallInst>(&i);
      if (ci && ci->getCalledFunction() && ci->getCalledFunction()->getName() == "__dp_func_entry") {
        function_entry_id = dyn_cast<ConstantInt>(ci->getArgOperand(2));
        break;
      }
    }
    if (function_entry_id == nullptr || function_entry_id->isZero()) {
      continue;
    }
    for (BasicBlock& bb : f) {
      if (!bb.isLandingPad()) {
        continue;
      }
      IRBuilder<> irb(&*bb.getFirstInsertionPt());
      irb.CreateCall(dp_landing_pad, {function_entry_id});
    }
  }
}
