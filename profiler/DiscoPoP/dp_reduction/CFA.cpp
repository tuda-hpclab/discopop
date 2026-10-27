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
#include <vector>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::DebugLoc;
using llvm::DILocation;
using llvm::dyn_cast;
using llvm::Function;
using llvm::Instruction;
using llvm::MDNode;
using llvm::SmallVector;
using llvm::SmallVectorImpl;
using llvm::StringRef;
using llvm::Value;

std::string dp_reduction::CFA(Function& f, llvm::Loop* l, int file_id) {
  std::string lid = "LOOPENDNOTFOUND";
  SmallVector<BasicBlock*, 8> exit_blocks;
  for (Function::iterator bb = f.begin(), be = f.end(); bb != be; ++bb) {
    BasicBlock* tmp_bb = &*bb;
    exit_blocks.clear();

    // Get the closest loop where tmpBB lives in.
    // (L == NULL) if tmpBB is not in any loop.

    // Check if tmpBB is the loop header (.cond) block.
    if (l != nullptr) {
      StringRef loop_type = tmp_bb->getName().split('.').first;

      // If tmpBB is the header block, get the exit blocks of the loop.
      if (l->hasDedicatedExits()) {
        // loop exits are in canonical form
        l->getUniqueExitBlocks(exit_blocks);
      } else {
        // loop exits are NOT in canonical form
        l->getExitBlocks(exit_blocks);
      }

      if (exit_blocks.size() == 0) {
        continue;
      }

      // When loop has break statement inside, exit blocks may contain
      // the if-else block containing the break. Since we always want
      // to find the real exit (.end) block, we need to check the
      // successors of the break statement(s).
      SmallVector<BasicBlock*, 4> real_exit_blocks;

      for (SmallVectorImpl<BasicBlock*>::iterator ei = exit_blocks.begin(), end = exit_blocks.end(); ei != end; ++ei) {
        StringRef exit_type = (*ei)->getName().split('.').first;
        if ((exit_type.str() == loop_type.str()) && ((*ei)->getName().find("end") != std::string::npos) &&
            (std::find(real_exit_blocks.begin(), real_exit_blocks.end(), *ei) == real_exit_blocks.end())) {
          real_exit_blocks.push_back(*ei);
        } else {
          // Changed TerminatorInst to Instruction
          Instruction* ti = (*ei)->getTerminator();
          assert(ti != NULL && "Exit block is not well formed!");
          const unsigned int num_succ = ti->getNumSuccessors();
          for (unsigned int i = 0; i < num_succ; ++i) {
            BasicBlock* succ = ti->getSuccessor(i);
            exit_type = succ->getName().split('.').first;
            if ((exit_type.str() == loop_type.str()) && (succ->getName().find("end") != std::string::npos) &&
                (std::find(real_exit_blocks.begin(), real_exit_blocks.end(), succ) == real_exit_blocks.end())) {
              real_exit_blocks.push_back(succ);
            }
          }
        }
      }

      if (real_exit_blocks.size() == 0) {
        continue;
      }

      // Check if entry block and exit block(s) have valid LID.
      bool has_valid_exit = false;
      for (SmallVectorImpl<BasicBlock*>::iterator ei = real_exit_blocks.begin(), end = real_exit_blocks.end();
           ei != end; ++ei) {
        has_valid_exit = dp_reduction::SanityCheck(*ei, file_id);
        if (has_valid_exit == true) {
          break;
        }
      }

      if (has_valid_exit) {
        for (SmallVectorImpl<BasicBlock*>::iterator ei = real_exit_blocks.begin(), end = real_exit_blocks.end();
             ei != end; ++ei) {
          BasicBlock* current_bb = *ei;
          const std::vector<Value*> args;
          LID lid = 0;

          for (BasicBlock::iterator bi = current_bb->begin(), ei = current_bb->end(); bi != ei; ++bi) {
            lid = dp_reduction::GetLid(&*bi, file_id);
            std::uint64_t ulid = static_cast<std::uint64_t>(lid);
            if (ulid != 0) {
              return std::to_string(ulid % kMaxLno);
            }
          }
        }
      }
    }
  }
  if (lid == "LOOPENDNOTFOUND") {
    if (MDNode* loop_id = l->getLoopID()) {
      DebugLoc start;
      // We use the first DebugLoc in the header as the start location of the
      // loop and if there is a second DebugLoc in the header we use it as end
      // location of the loop.
      bool found_end = false;
      for (unsigned i = 1, ie = loop_id->getNumOperands(); i < ie; ++i) {
        if (DILocation* dil = dyn_cast<DILocation>(loop_id->getOperand(i))) {
          if (!start) {
            if (found_end) {
              lid = std::to_string(DebugLoc(dil)->getLine());

              break;
            }
            found_end = true;
          }
        }
      }
    }
  }
  return lid;
}
