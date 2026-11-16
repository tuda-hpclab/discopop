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
#include "dot_discopop_default.hpp"

#include "llvm/IR/Constants.h"
#include "llvm/IR/GlobalVariable.h"
#include "llvm/Transforms/Utils/ModuleUtils.h"

using llvm::dyn_cast;
using llvm::errs;
using llvm::Module;
using llvm::Value;

namespace {

// Records the absolute path of the .discopop directory in the module (see dot_discopop_default.hpp). The constant is
// linkonce_odr, so the modules of a program agree on one, and listed as used, so that no optimization of the link drops
// it before the runtime reads it.
void RecordDotDiscopop(Module& m, const std::string& directory) {
  if (m.getNamedGlobal(kDotDiscopopDefaultSymbol) != nullptr) {
    return;
  }
  llvm::Constant* const value = llvm::ConstantDataArray::getString(m.getContext(), directory, true);
  auto* const variable = new llvm::GlobalVariable(m, value->getType(), true, llvm::GlobalValue::LinkOnceODRLinkage, value,
                                                  kDotDiscopopDefaultSymbol);
  variable->setVisibility(llvm::GlobalValue::HiddenVisibility);
  llvm::appendToUsed(m, {variable});
}

}  // namespace

bool DiscoPoP::DoInitialization(Module& m) {
  if (kDpDebug) {
    errs() << "DiscoPoP | 190: init pass DiscoPoP \n";
  }

  // prepare environment variables
  const char* tmp = std::getenv("DOT_DISCOPOP");
  if (tmp != nullptr && tmp[0] == '\0') {
    tmp = nullptr;  // an empty value is no value
  }
  if (tmp == nullptr) {
    // Without DOT_DISCOPOP: the .discopop directory of the project, the nearest one from the current directory (or the
    // source file) upwards. Every compiler call of a build finds the same one, wherever it compiles, and so does
    // the instrumented program (it is recorded in the object code below). The compiler wrappers have done this
    // already, which is the reason for DP_PROJECT_ROOT_DIR to be set as well.
    std::string shadowed;
    const std::string found = dputil::DiscoverDotDiscopop(m.getSourceFileName(), &shadowed);
    if (!found.empty()) {
      setenv("DOT_DISCOPOP", found.c_str(), 1);
      if (std::getenv("DP_PROJECT_ROOT_DIR") == nullptr) {
        setenv("DP_PROJECT_ROOT_DIR", std::filesystem::path(found).parent_path().c_str(), 1);
      }
      if (!shadowed.empty()) {
        std::cerr << "\nDiscoPoP: WARNING: using " << found << ", which holds no project configuration, although "
                  << shadowed << " does.\n"
                  << "          Remove the former if an earlier build left it behind, or set DOT_DISCOPOP.\n\n";
      }
      tmp = std::getenv("DOT_DISCOPOP");
    }
  }
  if (tmp == nullptr || tmp[0] != '/') {
    // A relative directory is resolved against the directory of each compiler call: a build that compiles in
    // several directories (every CMake build) spreads its data over several .discopop directories whose file
    // and instruction ids do not fit together, and the program does not find them when it is started elsewhere.
    std::cerr << "\nWARNING: DOT_DISCOPOP is " << (tmp == nullptr ? "not set" : "relative (" + std::string(tmp) + ")")
              << " and no .discopop directory exists in the current directory or above,\n"
              << "         so DiscoPoP writes to .discopop below the current directory\n"
              << "         (" << std::filesystem::current_path().string() << ").\n"
              << "         Create the directory in the root of the project (discopop_project_manager --init does)\n"
              << "         and every compiler call below it finds it, or set DOT_DISCOPOP to the same absolute path\n"
              << "         for every compiler call of the build and for the instrumented program.\n"
              << "         https://tuda-hpclab.github.io/discopop/setup/environment_variables/\n\n";
  }
  if (tmp == nullptr) {
    // DOT_DISCOPOP needs to be initialized
    setenv("DOT_DISCOPOP", ".discopop", 1);
  }
  const std::string tmp_str(std::getenv("DOT_DISCOPOP"));
  setenv("DOT_DISCOPOP_PROFILER", (tmp_str + "/profiler").data(), 1);
  if (tmp_str[0] == '/') {
    RecordDotDiscopop(m, tmp_str);
  }

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

  InitializeInstructionIdCounter();
  InitializeCallpathStateIdCounter();
  InitializeBBDepCounter();
  InitializeStaticMemoryRegionIDCounter();
  InitializeCuIdCounter();

  // CUGeneration
  {
    default_is_global_variable_value = false;
    this_module_ = &m;

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
