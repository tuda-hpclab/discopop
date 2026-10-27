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

#include <filesystem>
#include <iostream>
#include <string>

#include "DiscoPoP.hpp"

using llvm::dyn_cast;
using llvm::errs;
using llvm::Module;
using llvm::Value;

bool DiscoPoP::DoInitialization(Module& m) {
  if (kDpDebug) {
    errs() << "DiscoPoP | 190: init pass DiscoPoP \n";
  }

  // prepare environment variables
  const char* tmp = std::getenv("DOT_DISCOPOP");
  if (tmp == nullptr) {
    // DOT_DISCOPOP needs to be initialized
    setenv("DOT_DISCOPOP", ".discopop", 1);
  }
  const std::string tmp_str(std::getenv("DOT_DISCOPOP"));
  setenv("DOT_DISCOPOP_PROFILER", (tmp_str + "/profiler").data(), 1);

  // prepare .discopop directory if not present
  struct stat st1;
  if (stat(std::getenv("DOT_DISCOPOP"), &st1) == -1) {
    mkdir(std::getenv("DOT_DISCOPOP"), 0777);

    // check if HOME/.discopop_config directory in user folder exists
    const std::string user_home_dp_dir = (dputil::GetEnvOrDefault("HOME", "") + std::string("/.discopop_config"));
    struct stat st_dp_user;
    if (stat(user_home_dp_dir.c_str(), &st_dp_user) == -1) {
      // create .discopop_config folder in user directory to save overview of project .discopop folders
      mkdir(user_home_dp_dir.c_str(), 0777);
    }
    // create entry in HOME/.discopop_config/locations.txt
    std::ofstream project_overview_file;
    project_overview_file.open(user_home_dp_dir + std::string("/locations.txt"), std::ios_base::app);
    auto t = std::time(nullptr);
    auto tm = *std::localtime(&t);
    project_overview_file << std::put_time(&tm, "%d_%m_%Y-%H_%M_%S") << " "
                          << std::filesystem::absolute(std::string(std::getenv("DOT_DISCOPOP"))).string() << "\n";
    project_overview_file.close();
  }
  // prepare profiler directory if not present
  struct stat st2;
  if (stat(std::getenv("DOT_DISCOPOP_PROFILER"), &st2) == -1) {
    mkdir(std::getenv("DOT_DISCOPOP_PROFILER"), 0777);
  }
  // prepare statistics directory if not present
  struct stat st3;
  std::string tmp_str_2(dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler"));
  tmp_str_2 += "/statistics";
  if (stat(tmp_str_2.data(), &st3) == -1) {
    mkdir(tmp_str_2.data(), 0777);
  }

  // prepare target directory if not present
  const char* tmp2 = std::getenv("DP_PROJECT_ROOT_DIR");
  if (tmp2 == nullptr) {
    // DP_PROJECT_ROOT_DIR needs to be initialized
    std::cerr << "\nWARNING: No value for DP_PROJECT_ROOT_DIR found. \n";
    std::cerr << "         As a result, library functions might be "
                 "instrumented which can lead to\n";
    std::cerr << "         increased profiling times and unexpected behavior.\n";
    std::cerr << "         Please consider to specify the environment variable "
                 "and rebuild.\n";
    std::cerr << "         "
                 "https://tuda-hpclab.github.io/discopop/setup/"
                 "environment_variables/\n\n";
    // define fallback
    setenv("DP_PROJECT_ROOT_DIR", "/", 1);
  }

  file_id_cache.clear();

  // InstructionID assignment
  {
    // required for consecutive and unique assignment of instructionIDs across multiple modules.
    instruction_id_counter = 1;  // Reserve values 0 for "fallthrough" and 1 for "return"
    InitializeInstructionIdCounter();
    // instructionID assignment
    unique_llvm_ir_instruction_id_ = instruction_id_counter + 1;
  }

  // CallpathStateID assignment
  {
    // Unlike InstructionIDCounter above, the persisted CallpathStateIDCounter holds the next FREE
    // id rather than the last used one (runOnModule stores the path tree's next free id), so it is
    // used as-is. A value of 0 means no module has been processed yet; ids then start at 1, as 0 is
    // reserved for debugging and initialization purposes.
    callpath_state_id_counter = 0;
    InitializeCallpathStateIdCounter();
    if (callpath_state_id_counter == 0) {
      unique_callpath_state_id_ = 1;
    } else {
      unique_callpath_state_id_ = callpath_state_id_counter;
    }
  }

  // CUGeneration
  {
    cu_id_counter = 0;
    default_is_global_variable_value = false;
    this_module_ = &m;

    InitializeCuIdCounter();

    for (Module::global_iterator i = this_module_->global_begin(); i != this_module_->global_end(); i++) {
      Value* global_variable = dyn_cast<Value>(i);
      const std::string glo = std::string(global_variable->getName());
      if (glo.find(".") == glo.npos) {
        program_global_variables_set_.insert(glo);
        // originalVariablesSet.insert(glo);
      }
    }
  }
  // CUGeneration end

  // DPInstrumentation
  {
    // Export M to the outside
    this_module_ = &m;
    this_module_context_ = &(m.getContext());

    global_vars_.clear();
    structs_.clear();
    CollectDebugInfo();

    // Initialize variables needed
    SetupDataTypes();
    SetupCallbacks();

    // Check loop parallelism?
    if (kClCheckLoopPar) {
      if (kDpDebug) {
        errs() << "check loop parallelism \n";
      }
      loop_id_ = 0;
    } else {
      loop_id_ = -1;
    }
  }
  // DPInstrumentation end

  // DPInstrumentationOmission
  {
    hybrid_analysis_.emplace(m);
  }
  // DPInstrumentationOmission end

  return true;
}
