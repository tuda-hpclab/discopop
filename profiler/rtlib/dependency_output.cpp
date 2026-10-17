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

#include <cstdint>
#include <iostream>
#include <string>
#include <unordered_set>

#include "debug_print.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "timer.hpp"

namespace dp {

// hybrid analysis
void GenerateStringDepMap() {
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = MakeDebugPrint("generateStringDepMap");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kGenerateStringDepMap);
#endif

  for (auto& dline : *all_deps) {
    if (dline.first) {
      //  unpack dline.first (lid) to instructionID and callpathStateID
      std::uint32_t dline_first_inst_id = (dline.first & 0xFFFFFFFF);
      std::uint32_t dline_first_callpath_state_id = ((dline.first & 0xFFFFFFFF00000000) >> 32);
      const std::string unpacked_lid =
          std::to_string(dline_first_inst_id) + "@" +
          std::to_string(dline_first_callpath_state_id);  // use instructionID instead of lineID
      std::unordered_set<std::string> line_deps;
      for (auto& d : dline.second) {
        std::string dep = "";
        switch (d.type) {
          case kRaw:
            dep += "RAW";
            break;
          case kWar:
            dep += "WAR";
            break;
          case kWaw:
            dep += "WAW";
            break;
          case kInit:
            dep += "INIT";
            break;
          default:
            break;
        }

        // unpack d.depOn to instructionID and callpathStateID
        std::uint32_t d_dep_on_inst_id = (d.dep_on & 0xFFFFFFFF);
        std::uint32_t d_dep_on_callpath_state_id = ((d.dep_on & 0xFFFFFFFF00000000) >> 32);
        dep += ' ' + std::to_string(d_dep_on_inst_id) + "@" +
               std::to_string(d_dep_on_callpath_state_id);  // use unpacked information instead of lineID

        dep += "|" + std::string(d.var);
        dep += "(" + std::to_string(d.aa_var) + ")";

        line_deps.insert(dep);
      }

      if (out_put_deps->count(unpacked_lid) == 0) {
        (*out_put_deps)[unpacked_lid] = line_deps;
      } else {
        (*out_put_deps)[unpacked_lid].insert(line_deps.begin(), line_deps.end());
      }
    }
  }
}

void OutputDeps() {
#ifdef DP_RTLIB_VERBOSE
  const auto debug_print = MakeDebugPrint("outputDeps");
#endif
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kOutputDeps);
#endif

  for (const auto& pair : *out_put_deps) {
    *out << pair.first << " NOM ";
    for (const auto& dep : pair.second) {
      *out << ' ' << dep;
    }
    *out << std::endl;
  }
}
// End HA

}  // namespace dp
