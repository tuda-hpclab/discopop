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

void DiscoPoP::assign_instruction_ids_to_dp_reduction_functions(Module &M){
  for (Function &F : M) {
    for(BasicBlock &BB: F){
      for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
        auto instruction = &*BI;
        if(isa<CallInst>(instruction)){
          auto ci = cast<CallInst>(BI);
          Function* F = ci->getCalledFunction();
          if(F){
            auto fn = F->getName();
            if (fn.find("__dp_loop_incr") != string::npos)
            {
              // assign missing unique instruction id
              LLVMContext& ctx = BI->getContext();
              int32_t llvm_ir_instruction_id = unique_llvm_ir_instruction_id++;
              MDNode* N = MDNode::get(ctx, MDString::get(ctx, "dp.md.instr.id:"+to_string(llvm_ir_instruction_id)));
              BI->setMetadata("dp.md.instr.id", N);
              // fill instructionID to lineID mapping file
              *instructionID_to_lineID_file << to_string(llvm_ir_instruction_id) << " " << decodeLID(getLID(&*BI, fileID)) << "\n";
            }
          }
        }
      }
    }
  }
}

void DiscoPoP::update_argument_instruction_ids(Module &M){
  cout << "Updating argument instruction ids...\n";
  for (Function &F : M) {
    for(BasicBlock &BB: F){
      for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
        auto instruction = &*BI;
        if(isa<CallInst>(instruction)){
          auto ci = cast<CallInst>(BI);
          Function* F = ci->getCalledFunction();
          if(F){
            auto fn = F->getName();
            if (fn.find("__dp_loop_entry") != string::npos)
            {
              // Get InstructionID of callinstruction
              MDNode* md = BI->getMetadata("dp.md.instr.id");
              int32_t callInstructionID = 0;
              if(md){
                // Metadata exists
                std::string callInstructionID_str = cast<MDString>(md->getOperand(0))->getString().str();
                callInstructionID_str.erase(0, 15);
                callInstructionID = stoi(callInstructionID_str);
              }
              // update the function argument
              if(callInstructionID != 0){
                ci->setArgOperand(2, ConstantInt::get(Int32, callInstructionID));
              }
            }
            if (fn.find("__dp_loop_incr") != string::npos)
            {
              // Get InstructionID of callinstruction
              MDNode* md = BI->getMetadata("dp.md.instr.id");
              int32_t callInstructionID = 0;
              if(md){
                // Metadata exists
                std::string callInstructionID_str = cast<MDString>(md->getOperand(0))->getString().str();
                callInstructionID_str.erase(0, 15);
                callInstructionID = stoi(callInstructionID_str);
              }
              // update the function argument
              if(callInstructionID != 0){
                ci->setArgOperand(1, ConstantInt::get(Int32, callInstructionID));
              }
            }
            if (fn == "__dp_func_entry")
            {
              // the instruction id of the entry call identifies the function at runtime, see
              // callpath_function_entries.txt
              int32_t callInstructionID = get_dp_instruction_id(&*BI);
              if(callInstructionID != 0){
                ci->setArgOperand(2, ConstantInt::get(Int32, callInstructionID));
              }
            }
            if (fn.find("__dp_loop_exit") != string::npos)
            {
              // Get InstructionID of callinstruction
              MDNode* md = BI->getMetadata("dp.md.instr.id");
              int32_t callInstructionID = 0;
              if(md){
                // Metadata exists
                std::string callInstructionID_str = cast<MDString>(md->getOperand(0))->getString().str();
                callInstructionID_str.erase(0, 15);
                callInstructionID = stoi(callInstructionID_str);
              }
              // update the function argument
              if(callInstructionID != 0){
                ci->setArgOperand(2, ConstantInt::get(Int32, callInstructionID));
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
void DiscoPoP::instrument_landing_pads(Module &M){
  FunctionCallee DpLandingPad = M.getOrInsertFunction("__dp_landing_pad", Type::getVoidTy(M.getContext()), Int32);
  for (Function &F : M) {
    if (F.isDeclaration()) {
      continue;
    }
    // the function entry id is the last argument of the function's __dp_func_entry call
    ConstantInt* function_entry_id = nullptr;
    for (Instruction &I : F.getEntryBlock()) {
      auto ci = dyn_cast<CallInst>(&I);
      if (ci && ci->getCalledFunction() && ci->getCalledFunction()->getName() == "__dp_func_entry") {
        function_entry_id = dyn_cast<ConstantInt>(ci->getArgOperand(2));
        break;
      }
    }
    if (function_entry_id == nullptr || function_entry_id->isZero()) {
      continue;
    }
    for (BasicBlock &BB : F) {
      if (!BB.isLandingPad()) {
        continue;
      }
      IRBuilder<> IRB(&*BB.getFirstInsertionPt());
      IRB.CreateCall(DpLandingPad, {function_entry_id});
    }
  }
}
