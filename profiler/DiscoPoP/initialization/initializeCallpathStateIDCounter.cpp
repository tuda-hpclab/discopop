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

void DiscoPoP::initializeCallpathStateIDCounter() {
  std::string CallpathStateCounterFile(getenv("DOT_DISCOPOP_PROFILER"));
  CallpathStateCounterFile += "/DP_CallpathStateIDCounter.txt";
  if (dputil::fexists(CallpathStateCounterFile)) {
    std::fstream inCallpathStateIDCounter(CallpathStateCounterFile, std::ios_base::in);
    ;
    inCallpathStateIDCounter >> CallpathStateIDCounter;
    inCallpathStateIDCounter.close();
  }
}
