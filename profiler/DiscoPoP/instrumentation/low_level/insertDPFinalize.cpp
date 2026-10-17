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

#include "DiscoPoP.hpp"

void DiscoPoP::InsertDpFinalize(llvm::Instruction* before) {
  LID const lid = dputil::GetLid(before, file_id);
  assert((lid > 0) && "Returning on an invalid LID.");
  llvm::IRBuilder<> irb(before);
  irb.CreateCall(dp_finalize_, LidConstant(lid));
}
