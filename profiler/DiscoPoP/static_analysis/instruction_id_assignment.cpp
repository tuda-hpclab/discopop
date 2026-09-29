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
