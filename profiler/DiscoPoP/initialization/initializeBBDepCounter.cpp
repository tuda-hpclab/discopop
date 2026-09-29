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

void DiscoPoP::initializeBBDepCounter() {

  std::string BBDepCounterFile(getenv("DOT_DISCOPOP_PROFILER"));
  BBDepCounterFile += "/DP_BBDepCounter.txt";
  if (dputil::fexists(BBDepCounterFile)) {
    std::fstream inBBDepCounter(BBDepCounterFile, std::ios_base::in);
    ;
    inBBDepCounter >> bbDepCount;
    inBBDepCounter.close();
  }
}
