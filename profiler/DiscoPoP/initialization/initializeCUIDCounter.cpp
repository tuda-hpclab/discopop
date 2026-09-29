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

void DiscoPoP::initializeCUIDCounter() {
  std::string CUCounterFile(getenv("DOT_DISCOPOP_PROFILER"));
  CUCounterFile += "/DP_CUIDCounter.txt";
  if (dputil::fexists(CUCounterFile)) {
    std::fstream inCUIDCounter(CUCounterFile, std::ios_base::in);
    ;
    inCUIDCounter >> CUIDCounter;
    inCUIDCounter.close();
  }
}
