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

std::string DiscoPoP::dp_reduction_CFA(Function &F, llvm::Loop *L, int file_id) {
  std::string lid = "LOOPENDNOTFOUND";
  SmallVector<BasicBlock *, 8> ExitBlocks;
  for (Function::iterator BB = F.begin(), BE = F.end(); BB != BE; ++BB) {
    BasicBlock *tmpBB = &*BB;
    ExitBlocks.clear();

    // Get the closest loop where tmpBB lives in.
    // (L == NULL) if tmpBB is not in any loop.

    // Check if tmpBB is the loop header (.cond) block.
    if (L != NULL) {
      StringRef loopType = tmpBB->getName().split('.').first;

      // If tmpBB is the header block, get the exit blocks of the loop.
      if (L->hasDedicatedExits()) {
        // loop exits are in canonical form
        L->getUniqueExitBlocks(ExitBlocks);
      } else {
        // loop exits are NOT in canonical form
        L->getExitBlocks(ExitBlocks);
      }

      if (ExitBlocks.size() == 0) {
        continue;
      }

      // When loop has break statement inside, exit blocks may contain
      // the if-else block containing the break. Since we always want
      // to find the real exit (.end) block, we need to check the
      // successors of the break statement(s).
      SmallVector<BasicBlock *, 4> RealExitBlocks;

      for (SmallVectorImpl<BasicBlock *>::iterator EI = ExitBlocks.begin(), END = ExitBlocks.end(); EI != END; ++EI) {
        StringRef exitType = (*EI)->getName().split('.').first;
        if ((exitType.str() == loopType.str()) && ((*EI)->getName().find("end") != string::npos) &&
            (std::find(RealExitBlocks.begin(), RealExitBlocks.end(), *EI) == RealExitBlocks.end())) {
          RealExitBlocks.push_back(*EI);
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
            }
          }
        }
      }

      if (RealExitBlocks.size() == 0) {
        continue;
      }

      // Check if entry block and exit block(s) have valid LID.
      bool hasValidExit = false;
      for (SmallVectorImpl<BasicBlock *>::iterator EI = RealExitBlocks.begin(), END = RealExitBlocks.end(); EI != END;
           ++EI) {
        hasValidExit = dp_reduction_sanityCheck(*EI, file_id);
        if (hasValidExit == true)
          break;
      }

      if (hasValidExit) {
        for (SmallVectorImpl<BasicBlock *>::iterator EI = RealExitBlocks.begin(), END = RealExitBlocks.end(); EI != END;
             ++EI) {
          BasicBlock *currentBB = *EI;
          vector<Value *> args;
          LID lid = 0;

          for (BasicBlock::iterator BI = currentBB->begin(), EI = currentBB->end(); BI != EI; ++BI) {
            lid = dp_reduction_getLID(&*BI, file_id);
            uint64_t ulid = (uint64_t)lid;
            if (ulid != 0) {
              return to_string(ulid % 16384);
            }
          }
        }
      }
    }
  }
  if (lid == "LOOPENDNOTFOUND") {
    if (MDNode *LoopID = L->getLoopID()) {
      DebugLoc Start;
      // We use the first DebugLoc in the header as the start location of the
      // loop and if there is a second DebugLoc in the header we use it as end
      // location of the loop.
      bool foundEnd = false;
      for (unsigned i = 1, ie = LoopID->getNumOperands(); i < ie; ++i) {
        if (DILocation *DIL = dyn_cast<DILocation>(LoopID->getOperand(i))) {
          if (!Start) {
            if (foundEnd) {
              lid = to_string(DebugLoc(DIL)->getLine());

              break;
            } else {
              foundEnd = true;
            }
          }
        }
      }
    }
  }
  return lid;
}
