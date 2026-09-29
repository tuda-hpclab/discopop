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

#include "../loop/LoopInfo.hpp"

#include <fstream>
#include <iostream>
#include <vector>

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_loop_output() {
  if (loop_manager == nullptr || loop_manager->is_done()) {
    return;
  }

  std::cout << "Outputting instrumentation results... ";

  std::ifstream ifile;
  std::string line;
  std::ofstream ofile;

  // get meta information about the loops
  std::vector<loop_info_t> loop_infos;
  loop_infos.push_back(loop_info_t()); // dummy
  const char *discopop_profiler_env = getenv("DOT_DISCOPOP_PROFILER");
  if (discopop_profiler_env == NULL) {
    return;
  }
  std::string tmp(discopop_profiler_env);
  tmp += "/loop_meta.txt";
  ifile.open(tmp.data());
  while (std::getline(ifile, line)) {
    loop_info_t loop_info;
    int cnt = sscanf(line.c_str(), "%d %d %d", &loop_info.file_id_, &loop_info.loop_id_, &loop_info.line_nr_);
    if (cnt == 3) {
      loop_infos.push_back(loop_info);
    }
  }
  ifile.close();

  // output information about the loops
  std::string tmp2(discopop_profiler_env);
  tmp2 += "/loop_counter_output.txt";
  ofile.open(tmp2.data());
  const auto &loop_counters = loop_manager->get_loop_counters();

  for (auto i = 1; i < loop_counters.size(); ++i) {
    loop_info_t &loop_info = loop_infos[i];
    ofile << loop_info.file_id_ << " ";
    ofile << loop_info.line_nr_ << " ";
    ofile << loop_counters[i] << "\n";
  }
  ofile.close();

  std::cout << "done" << std::endl;

  loop_manager->set_done();
}
}

} // namespace __dp
