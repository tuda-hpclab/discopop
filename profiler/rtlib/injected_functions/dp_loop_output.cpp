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

#include "../output_paths.hpp"
#include "../runtimeFunctionsGlobals.hpp"

#include "../loop/LoopInfo.hpp"

#include <fstream>
#include <iostream>
#include <unordered_map>
#include <vector>

namespace __dp {

/******* Instrumentation function *******/
extern "C" {

void __dp_loop_output() {
  if (!manager_globals_constructed() || loop_manager->is_done()) {
    return;
  }

  std::cout << "Outputting instrumentation results... ";

  std::ifstream ifile;
  std::string line;
  std::ofstream ofile;

  // get meta information about the loops, by loop id -- loop_meta.txt lists the loops in
  // the order the pass registered them, which is not the order of their ids.
  std::unordered_map<int, loop_info_t> loop_infos;
  ifile.open(profiler_output_path("loop_meta.txt"));
  while (std::getline(ifile, line)) {
    loop_info_t loop_info;
    int cnt = sscanf(line.c_str(), "%d %d %d", &loop_info.file_id_, &loop_info.loop_id_, &loop_info.line_nr_);
    if (cnt == 3) {
      loop_infos[loop_info.loop_id_] = loop_info;
    }
  }
  ifile.close();

  // output information about the loops
  ofile.open(profiler_output_path("loop_counter_output.txt"));
  const auto &loop_counters = loop_manager->get_loop_counters();

  // The counters are indexed by loop id, starting at 0. Reading them from 1 and pairing
  // them with the lines of loop_meta.txt in file order named every count after the wrong
  // loop and left the last one out: nested_loops reported the middle loop's 65536
  // iterations for its outer loop, and never mentioned its innermost one.
  for (std::size_t i = 0; i < loop_counters.size(); ++i) {
    const auto loop_info = loop_infos.find(static_cast<int>(i));
    if (loop_info == loop_infos.end()) {
      // A loop the pass counted but could not describe. Nothing to name it by.
      continue;
    }
    ofile << loop_info->second.file_id_ << " ";
    ofile << loop_info->second.line_nr_ << " ";
    ofile << loop_counters[i] << "\n";
  }
  ofile.close();

  std::cout << "done" << std::endl;

  loop_manager->set_done();
}
}

} // namespace __dp
