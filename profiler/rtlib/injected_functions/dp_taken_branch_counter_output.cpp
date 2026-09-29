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

#include "../DPTypes.hpp"

#include "../runtimeFunctionsGlobals.hpp"

#include <fstream>
#include <iostream>
#include <string>

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_taken_branch_counter_output() {
  std::cout << "Outputting instrumentation results (taken branches)... ";

  std::ofstream ofile;

  // output information about the loops
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  tmp += "/cu_taken_branch_counter_output.txt";
  ofile.open(tmp.data());

  for (auto pair : cuec) {
    ofile << pair.first << ";" << pair.second << "\n";
  }

  ofile.close();

  std::cout << "done" << std::endl;
}
}

} // namespace __dp
