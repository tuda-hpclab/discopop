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

using llvm::BasicBlock;
using llvm::DebugLoc;
using llvm::errs;
using llvm::Function;
using llvm::Instruction;
using llvm::Loop;
using llvm::LoopInfo;
using llvm::SmallVector;
using llvm::SmallVectorImpl;
using llvm::StringRef;

// Control-flow analysis functions

void DiscoPoP::CFA(Function& f, LoopInfo& li, const std::map<Loop*, std::string>& loop_to_pet_node_id) {
  SmallVector<BasicBlock*, 8> exit_blocks;
  for (Function::iterator bb = f.begin(), be = f.end(); bb != be; ++bb) {
    BasicBlock* tmp_bb = &*bb;
    exit_blocks.clear();

    // Get the closest loop where tmpBB lives in.
    // (L == NULL) if tmpBB is not in any loop.
    Loop* l = li.getLoopFor(tmp_bb);

    // Check if tmpBB is the loop header (.cond) block.
    if (l != nullptr && li.isLoopHeader(tmp_bb)) {
      StringRef loop_type = tmp_bb->getName().split('.').first;
      if (kDpDebug) {
        errs() << "loop [" << loop_type << "] header: " << tmp_bb->getName() << "\n";
      }

      // If tmpBB is the header block, get the exit blocks of the loop.
      if (l->hasDedicatedExits()) {
        // loop exits are in canonical form
        l->getUniqueExitBlocks(exit_blocks);
      } else {
        // loop exits are NOT in canonical form
        l->getExitBlocks(exit_blocks);
      }

      if (exit_blocks.size() == 0) {
        errs() << "WARNING: loop at " << tmp_bb << " is ignored: exit BB not found.\n";
        continue;
      }

      // When loop has break statement inside, exit blocks may contain
      // the if-else block containing the break. Since we always want
      // to find the real exit (.end) block, we need to check the
      // successors of the break statement(s).
      SmallVector<BasicBlock*, 4> real_exit_blocks;
      if (kDpDebug) {
        errs() << "loop exits:";
      }
      for (SmallVectorImpl<BasicBlock*>::iterator ei = exit_blocks.begin(), end = exit_blocks.end(); ei != end; ++ei) {
        StringRef exit_type = (*ei)->getName().split('.').first;
        if ((exit_type.str() == loop_type.str()) && ((*ei)->getName().find("end") != std::string::npos) &&
            (std::find(real_exit_blocks.begin(), real_exit_blocks.end(), *ei) == real_exit_blocks.end())) {
          real_exit_blocks.push_back(*ei);
          if (kDpDebug) {
            errs() << " " << (*ei)->getName();
          }
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
              if (kDpDebug) {
                errs() << " " << succ->getName();
              }
            }
          }
        }
      }
      if (kDpDebug) {
        errs() << "\n";
      }

      // assert((RealExitBlocks.size() == 1) && "Loop has more than one real
      // exit block!");
      if (real_exit_blocks.size() == 0) {
        if (kDpVerbose) {
          errs() << "WARNING: loop at " << tmp_bb << " is ignored: exit blocks are not well formed.\n";
        }
        continue;
      }

      // Check if entry block and exit block(s) have valid LID.
      const bool has_valid_entry = SanityCheck(tmp_bb);
      bool has_valid_exit = false;
      for (SmallVectorImpl<BasicBlock*>::iterator ei = real_exit_blocks.begin(), end = real_exit_blocks.end();
           ei != end; ++ei) {
        has_valid_exit = GetLoopExitLid(*ei, l) > 0;
        if (has_valid_exit == true) {
          break;
        }
      }

      if (has_valid_entry && has_valid_exit) {
        auto tmp_loop_id = GetOrRegisterLoopId(l);
        // remember the loop's identity for loopstate_positions.txt (see buildStaticCalltree)
        LoopIdentity identity;
        auto pet_node = loop_to_pet_node_id.find(l);
        identity.pet_node_id = pet_node != loop_to_pet_node_id.end() ? pet_node->second : "-";
        DebugLoc start_loc = l->getStartLoc();
        identity.start_location = start_loc ? dputil::DecodeLid(dputil::EncodeLid(file_id, start_loc.getLine()))
                                            : std::to_string(file_id) + ":0";
        loop_id_to_identity[tmp_loop_id] = identity;
        // Instrument loop header block.
        InstrumentLoopEntry(tmp_bb, tmp_loop_id);

        // Instrument loop exit block(s).
        for (SmallVectorImpl<BasicBlock*>::iterator ei = real_exit_blocks.begin(), end = real_exit_blocks.end();
             ei != end; ++ei) {
          InstrumentLoopExit(*ei, tmp_loop_id, l);
        }
      }
    }
  }
}
