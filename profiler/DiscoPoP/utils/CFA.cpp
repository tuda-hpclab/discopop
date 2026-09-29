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

// Control-flow analysis functions

void DiscoPoP::CFA(Function &F, LoopInfo &LI) {
  SmallVector<BasicBlock *, 8> ExitBlocks;
  for (Function::iterator BB = F.begin(), BE = F.end(); BB != BE; ++BB) {
    BasicBlock *tmpBB = &*BB;
    ExitBlocks.clear();

    // Get the closest loop where tmpBB lives in.
    // (L == NULL) if tmpBB is not in any loop.
    Loop *L = LI.getLoopFor(tmpBB);

    // Check if tmpBB is the loop header (.cond) block.
    if (L != NULL && LI.isLoopHeader(tmpBB)) {
      StringRef loopType = tmpBB->getName().split('.').first;
      if (DP_DEBUG) {
        errs() << "loop [" << loopType << "] header: " << tmpBB->getName() << "\n";
      }

      // If tmpBB is the header block, get the exit blocks of the loop.
      if (L->hasDedicatedExits()) {
        // loop exits are in canonical form
        L->getUniqueExitBlocks(ExitBlocks);
      } else {
        // loop exits are NOT in canonical form
        L->getExitBlocks(ExitBlocks);
      }

      if (ExitBlocks.size() == 0) {
        errs() << "WARNING: loop at " << tmpBB << " is ignored: exit BB not found.\n";
        continue;
      }

      // When loop has break statement inside, exit blocks may contain
      // the if-else block containing the break. Since we always want
      // to find the real exit (.end) block, we need to check the
      // successors of the break statement(s).
      SmallVector<BasicBlock *, 4> RealExitBlocks;
      if (DP_DEBUG) {
        errs() << "loop exits:";
      }
      for (SmallVectorImpl<BasicBlock *>::iterator EI = ExitBlocks.begin(), END = ExitBlocks.end(); EI != END; ++EI) {
        StringRef exitType = (*EI)->getName().split('.').first;
        if ((exitType.str() == loopType.str()) && ((*EI)->getName().find("end") != string::npos) &&
            (std::find(RealExitBlocks.begin(), RealExitBlocks.end(), *EI) == RealExitBlocks.end())) {
          RealExitBlocks.push_back(*EI);
          if (DP_DEBUG) {
            errs() << " " << (*EI)->getName();
          }
        } else {
          // Changed TerminatorInst to Instruction
          Instruction *TI = (*EI)->getTerminator();
          assert(TI != NULL && "Exit block is not well formed!");
          unsigned int numSucc = TI->getNumSuccessors();
          for (unsigned int i = 0; i < numSucc; ++i) {
            BasicBlock *succ = TI->getSuccessor(i);
            exitType = succ->getName().split('.').first;
            if ((exitType.str() == loopType.str()) && (succ->getName().find("end") != string::npos) &&
                (std::find(RealExitBlocks.begin(), RealExitBlocks.end(), succ) == RealExitBlocks.end())) {
              RealExitBlocks.push_back(succ);
              if (DP_DEBUG) {
                errs() << " " << succ->getName();
              }
            }
          }
        }
      }
      if (DP_DEBUG) {
        errs() << "\n";
      }

      // assert((RealExitBlocks.size() == 1) && "Loop has more than one real
      // exit block!");
      if (RealExitBlocks.size() == 0) {
        if (DP_VERBOSE) {
          errs() << "WARNING: loop at " << tmpBB << " is ignored: exit blocks are not well formed.\n";
        }
        continue;
      }

      // Check if entry block and exit block(s) have valid LID.
      bool hasValidEntry = sanityCheck(tmpBB);
      bool hasValidExit = false;
      for (SmallVectorImpl<BasicBlock *>::iterator EI = RealExitBlocks.begin(), END = RealExitBlocks.end(); EI != END;
           ++EI) {
        hasValidExit = sanityCheck(*EI);
        if (hasValidExit == true)
          break;
      }

      if (hasValidEntry && hasValidExit) {
        auto tmp_loop_id = get_or_register_loop_id(L);
        // Instrument loop header block.
        instrumentLoopEntry(tmpBB, tmp_loop_id);


        // Instrument loop exit block(s).
        for (SmallVectorImpl<BasicBlock *>::iterator EI = RealExitBlocks.begin(), END = RealExitBlocks.end(); EI != END;
             ++EI) {
          instrumentLoopExit(*EI, tmp_loop_id);
        }
      }
    }
  }
}
