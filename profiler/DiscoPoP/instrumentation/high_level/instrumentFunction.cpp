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

#include "../../DiscoPoP.hpp"

// iterates over all loops in a function and calls 'instrument_loop' for each
// one
void DiscoPoP::instrument_function(llvm::Function *function, map<string, string> *trueVarNamesFromMetadataMap, llvm::LoopInfo &loop_info) {

  // get the corresponding file id
  int32_t tmp_file_id;
  determineFileID(*function, tmp_file_id);
  if (tmp_file_id == 0) {
    return;
  }

  //llvm::LoopInfo &loop_info = getAnalysis<llvm::LoopInfoWrapperPass>(*function).getLoopInfo();

  for (auto loop_it = loop_info.begin(); loop_it != loop_info.end(); ++loop_it) {
    instrument_loop(*function, tmp_file_id, *loop_it, loop_info, trueVarNamesFromMetadataMap);
  }
}
