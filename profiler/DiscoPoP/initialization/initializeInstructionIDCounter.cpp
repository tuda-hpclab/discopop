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

void DiscoPoP::initializeInstructionIDCounter() {
  std::string InstructionCounterFile(getenv("DOT_DISCOPOP_PROFILER"));
  InstructionCounterFile += "/DP_InstructionIDCounter.txt";
  if (dputil::fexists(InstructionCounterFile)) {
    std::fstream inInstructionIDCounter(InstructionCounterFile, std::ios_base::in);
    ;
    inInstructionIDCounter >> InstructionIDCounter;
    inInstructionIDCounter.close();
  }
}
