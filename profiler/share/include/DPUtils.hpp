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

#pragma once

#include "llvm-c/Core.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/Statistic.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/ADT/ilist.h"
#include "llvm/Analysis/DominanceFrontier.h"
#include "llvm/Analysis/LoopInfo.h"
#include "llvm/Analysis/Passes.h"
#include "llvm/Analysis/RegionInfo.h"
#include "llvm/Analysis/RegionIterator.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/CFG.h"
#include "llvm/IR/DataLayout.h"
#include "llvm/IR/DebugInfo.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/DerivedTypes.h"
#include "llvm/IR/Dominators.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instruction.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/LLVMContext.h"
#include "llvm/IR/LegacyPassManager.h"
#include "llvm/IR/Metadata.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/IR/Type.h"
#include "llvm/IR/User.h"
#include "llvm/IR/Value.h"
#include "llvm/Pass.h"
#include "llvm/PassRegistry.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/Debug.h"
#include "llvm/Support/raw_ostream.h"

#include "lid_constants.hpp"

// Guard legacy LLVM includes (may be missing in newer LLVM versions)
#if __has_include(<llvm/Transforms/IPO/PassManagerBuilder.h>)
#include <llvm/Transforms/IPO/PassManagerBuilder.h>
#endif

#if __has_include(<llvm/Transforms/Instrumentation.h>)
#include <llvm/Transforms/Instrumentation.h>
#endif

#if __has_include(<llvm/Passes/PassBuilder.h>)
#include <llvm/Passes/PassBuilder.h>
#endif

#include <assert.h>
#include <stdint.h>
#include <unistd.h>

#include <fstream>
#include <iostream>  // std::cerr
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// extern cl::opt <string> FileMappingPath;
// The path of FileMapping.txt; empty until the first file id is determined.
std::string& FileMappingPath();
extern llvm::cl::opt<bool> dp_memory_profiling_skip_function_arguments;
namespace dputil {

// value of the environment variable `name`, or `fallback` if it is not set (std::string(nullptr) is
// undefined behaviour); the fallbacks match the ones the pass's doInitialization sets
inline std::string GetEnvOrDefault(const char* name, const char* fallback) {
  const char* value = getenv(name);
  return std::string(value != nullptr ? value : fallback);
}

inline std::string DecodeLid(int64_t lid) {
  if (lid == 0) {
    return "*";
  }

  std::stringstream ss;
  const uint32_t ulid = static_cast<uint32_t>(lid);

  ss << (ulid >> kLidSize) << ":" << ulid % kMaxLno;
  return ss.str();
}

inline std::vector<std::string>* Split(const std::string& input, char delim) {
  std::vector<std::string>* substrings = new std::vector<std::string>();
  std::istringstream input_string_stream(input);
  std::string sub;

  while (getline(input_string_stream, sub, delim)) {
    substrings->push_back(sub);
  }

  return substrings;
}

inline bool FileExists(const std::string& filename) {
  const std::ifstream ifile(filename.c_str());

  if (ifile.fail()) {
    return false;
  }
  return true;
}

int32_t GetFileId(const std::string& file_mapping, const std::string& full_path_name);

// Encode a file id and a line number as LID, see lid_constants.hpp. Returns 0 ("no location") and warns
// once per file id if one of them does not fit into the LID.
int64_t EncodeLid(int32_t file_id, int64_t line);

int64_t GetLid(llvm::Instruction* bi, int32_t& file_id);

void DetermineFileId(llvm::Function& f, int32_t& file_id);

std::string GetExeDir();

class VariableNameFinder {
 public:
  explicit VariableNameFinder(llvm::Module& m);

  std::string GetVarName(const llvm::Value* v);
};

}  // namespace dputil
