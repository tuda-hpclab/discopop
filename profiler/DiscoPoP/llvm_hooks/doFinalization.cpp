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

bool DiscoPoP::DoFinalization(llvm::Module& m) {
  // DPInstrumentationOmission
  hybrid_analysis_->Finalize(m);
  // DPInstrumentationOmission end
  return true;
}
