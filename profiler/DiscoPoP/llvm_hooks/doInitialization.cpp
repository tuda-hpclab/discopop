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
#include <filesystem>

bool DiscoPoP::doInitialization(Module &M) {
  if (DP_DEBUG) {
    errs() << "DiscoPoP | 190: init pass DiscoPoP \n";
  }

  // prepare environment variables
  char const *tmp = getenv("DOT_DISCOPOP");
  if (tmp == NULL) {
    // DOT_DISCOPOP needs to be initialized
    setenv("DOT_DISCOPOP", ".discopop", 1);
  }
  std::string tmp_str(getenv("DOT_DISCOPOP"));
  setenv("DOT_DISCOPOP_PROFILER", (tmp_str + "/profiler").data(), 1);

  // prepare .discopop directory if not present
  struct stat st1;
  if (stat(getenv("DOT_DISCOPOP"), &st1) == -1) {
    mkdir(getenv("DOT_DISCOPOP"), 0777);

    // check if HOME/.discopop_config directory in user folder exists
    std::string user_home_dp_dir = (std::string(getenv("HOME")) + std::string("/.discopop_config"));
    struct stat st_dp_user;
    if (stat(user_home_dp_dir.c_str() , &st_dp_user) == -1) {
      // create .discopop_config folder in user directory to save overview of project .discopop folders
      mkdir(user_home_dp_dir.c_str(), 0777);
    }
    // create entry in HOME/.discopop_config/locations.txt
    std::ofstream project_overview_file;
    project_overview_file.open(user_home_dp_dir + std::string("/locations.txt"), std::ios_base::app);
    auto t = std::time(nullptr);
    auto tm = *std::localtime(&t);
    project_overview_file << std::put_time(&tm, "%d_%m_%Y-%H_%M_%S") << " " << std::filesystem::absolute(std::string(getenv("DOT_DISCOPOP"))).string() << "\n";
    project_overview_file.close();
  }
  // prepare profiler directory if not present
  struct stat st2;
  if (stat(getenv("DOT_DISCOPOP_PROFILER"), &st2) == -1) {
    mkdir(getenv("DOT_DISCOPOP_PROFILER"), 0777);
  }
  // prepare statistics directory if not present
  struct stat st3;
  std::string tmp_str_2(getenv("DOT_DISCOPOP_PROFILER"));
  tmp_str_2 += "/statistics";
  if (stat(tmp_str_2.data(), &st3) == -1) {
    mkdir(tmp_str_2.data(), 0777);
  }

  // prepare target directory if not present
  char const *tmp2 = getenv("DP_PROJECT_ROOT_DIR");
  if (tmp2 == NULL) {
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

  // InstructionID assignment
  {
    // required for consecutive and unique assignment of instructionIDs across multiple modules.
    InstructionIDCounter = 1;  // Reserve values 0 for "fallthrough" and 1 for "return"
    initializeInstructionIDCounter();
    // instructionID assignment
    unique_llvm_ir_instruction_id = InstructionIDCounter + 1;
  }

  // CallpathStateID assignment
  {
    // Unlike InstructionIDCounter above, the persisted CallpathStateIDCounter holds the next FREE
    // id rather than the last used one (runOnModule stores the path tree's next free id), so it is
    // used as-is. A value of 0 means no module has been processed yet; ids then start at 1, as 0 is
    // reserved for debugging and initialization purposes.
    CallpathStateIDCounter = 0;
    initializeCallpathStateIDCounter();
    if (CallpathStateIDCounter == 0) {
      unique_callpath_state_id = 1;
    } else {
      unique_callpath_state_id = CallpathStateIDCounter;
    }
  }


  // CUGeneration
  {
    CUIDCounter = 0;
    defaultIsGlobalVariableValue = false;
    ThisModule = &M;
    outCUIDCounter = NULL;

    initializeCUIDCounter();

    for (Module::global_iterator I = ThisModule->global_begin(); I != ThisModule->global_end(); I++) {
      Value *globalVariable = dyn_cast<Value>(I);
      string glo = string(globalVariable->getName());
      if (glo.find(".") == glo.npos) {
        programGlobalVariablesSet.insert(glo);
        // originalVariablesSet.insert(glo);
      }
    }
  }
  // CUGeneration end

  // DPInstrumentation
  {
    // Export M to the outside
    ThisModule = &M;
    ThisModuleContext = &(M.getContext());

    for (set<DIGlobalVariable *>::iterator it = GlobalVars.begin(); it != GlobalVars.end(); ++it) {
      GlobalVars.erase(it);
    }

    GlobalVars.clear();
    Structs.clear();
    collectDebugInfo();

    // Initialize variables needed
    setupDataTypes();
    setupCallbacks();

    // Check loop parallelism?
    if (ClCheckLoopPar) {
      if (DP_DEBUG) {
        errs() << "check loop parallelism \n";
      }
      loopID = 0;
    } else {
      loopID = -1;
    }

  }
  // DPInstrumentation end

  // DPInstrumentationOmission
  {
    bbDepCount = 0;

    initializeBBDepCounter();

    ReportBB = M.getOrInsertFunction("__dp_report_bb", Void, Int32);
    ReportBBPair = M.getOrInsertFunction("__dp_report_bb_pair", Void, Int32, Int32);
    BBState = M.getOrInsertFunction("__dp_bb_state", Int32);
    VNF = new dputil::VariableNameFinder(M);
  }
  // DPInstrumentationOmission end

  return true;
}
