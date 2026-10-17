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

#include "DPUtils.hpp"

#include <map>
#include <set>
#include <string>

#define DP_DEBUG_TYPE "dputils"

using dputil::DetermineFileId;
using dputil::EncodeLid;
using dputil::GetExeDir;
using dputil::GetFileId;
using dputil::GetLid;
using dputil::VariableNameFinder;
using llvm::AllocaInst;
using llvm::BasicBlock;
using llvm::BinaryOperator;
using llvm::ConstantInt;
using llvm::DebugLoc;
using llvm::DILocation;
using llvm::dyn_cast;
using llvm::errs;
using llvm::Function;
using llvm::GEPOperator;
using llvm::GetElementPtrInst;
using llvm::GlobalValue;
using llvm::GlobalVariable;
using llvm::Instruction;
using llvm::isa;
using llvm::LoadInst;
using llvm::MDNode;
using llvm::Module;
using llvm::SExtInst;
using llvm::StoreInst;
using llvm::StringRef;
using llvm::StructType;
using llvm::Value;

// cl::opt <string> FileMappingPath("fm-path", cl::init(""),
//                                  cl::desc("Specify file mapping location"),
//                                  cl::Hidden);
std::string& FileMappingPath() {
  // allocated once and never destroyed: an object with static storage duration must be trivially destructible
  static std::string& path = *new std::string();
  return path;
}

llvm::cl::opt<bool> dp_memory_profiling_skip_function_arguments(
    "memory-profiling-skip-function-arguments", llvm::cl::init(false),
    llvm::cl::desc("disable the memory profiling for allocations which belong to "
                   "function arguments"),
    llvm::cl::Hidden);

namespace dputil {

std::int32_t GetFileId(const std::string& /*file_mapping*/, const std::string& full_path_name) {
  // prepare environment variables
  if (FileMappingPath().length() == 0) {
    const char* tmp = std::getenv("DOT_DISCOPOP");
    if (tmp == nullptr) {
      // DOT_DISCOPOP needs to be initialized
      setenv("DOT_DISCOPOP", ".discopop", 1);
    }
    FileMappingPath() = std::getenv("DOT_DISCOPOP");
    FileMappingPath() += "/FileMapping.txt";
  }

  // check if path in DP_PROJECT_ROOT_DIR
  const std::string dp_project_dir(dputil::GetEnvOrDefault("DP_PROJECT_ROOT_DIR", "/"));
  if (full_path_name.find(dp_project_dir) == std::string::npos) {  // function defined outside project
    return 0;
  }

  // Keep FileMapping.txt in an in-memory cache. getFileID is called per-instruction, so
  // re-reading the file on every call dominates the pass runtime.
  static std::map<std::string, std::int32_t> file_id_cache;
  static std::int32_t next_file_id = 1;
  static bool file_mapping_loaded = false;

  auto load_file_mapping = [&]() {
    std::fstream file_mapping_file;
    file_mapping_file.open(FileMappingPath().data(), std::ios::in);
    if (file_mapping_file) {
      std::string tp;
      while (std::getline(file_mapping_file, tp)) {
        const std::size_t tab = tp.find("\t");
        if (tab == std::string::npos) {
          continue;
        }
        std::int32_t id = std::stoi(tp.substr(0, tab));
        const std::string file_name = tp.substr(tab + 1);
        file_id_cache[file_name] = id;
        if (id >= next_file_id) {
          next_file_id = id + 1;
        }
      }
      file_mapping_file.close();
    }
    file_mapping_loaded = true;
  };

  if (!file_mapping_loaded) {
    load_file_mapping();
  }

  // hot path: in-memory lookup, no file I/O
  auto cached = file_id_cache.find(full_path_name);
  if (cached != file_id_cache.end()) {
    return cached->second;
  }

  // Miss. FileMapping.txt is shared by all compiler processes of a build and is not
  // necessarily pre-generated (see the dp-fmap script), so a file unknown to this process may
  // well have been registered by a concurrently running one in the meantime. Re-read the file
  // before handing out a new id, otherwise two processes assign the same id to different
  // files. Only the miss path pays for this, the cached lookups above stay free.
  // NOTE: the append below remains racy - two processes missing at the same time still end up
  // with the same id. Removing that window requires locking the file.
  load_file_mapping();
  cached = file_id_cache.find(full_path_name);
  if (cached != file_id_cache.end()) {
    return cached->second;
  }

  // still unknown: assign a new id, persist it once, and cache it
  std::int32_t tempfid = next_file_id++;
  std::fstream file_mapping_file;
  file_mapping_file.open(FileMappingPath().data(), std::ios_base::app);
  file_mapping_file << tempfid << "\t" << full_path_name << "\n";
  file_mapping_file.close();
  file_id_cache[full_path_name] = tempfid;
  return tempfid;
  /*
  int32_t index = 0; // if the associated file id is not found, then we return 0
  string line;
  ifstream fileMap(fileMapping.c_str());

  if (fileMap.is_open()) {
      vector <string> *substrings = NULL;
      while (getline(fileMap, line)) {
          substrings = split(line, '\t');
          if (substrings->size() == 2) {
              string indexString = (*substrings)[0];
              string fileName = (*substrings)[1];
              if (fileName.compare(fullPathName) == 0) {
                  index = (int32_t) atoi(indexString.c_str());
                  break;
              }
          }
          delete substrings;
      }
      fileMap.close();
  }
  return index;
  */
}

std::int64_t EncodeLid(std::int32_t file_id, std::int64_t line) {
  static std::set<std::int32_t> warned_file_ids;
  if (file_id < 0 || file_id > kMaxFileId) {
    if (warned_file_ids.insert(file_id).second) {
      errs() << "DiscoPoP: warning: the file id " << file_id << " exceeds the maximum of " << kMaxFileId
             << " files, its instructions are not instrumented\n";
    }
    return 0;
  }
  if (line < 0 || line >= kMaxLno) {
    if (warned_file_ids.insert(file_id).second) {
      errs() << "DiscoPoP: warning: line " << line << " of the file with the id " << file_id
             << " exceeds the maximum of " << kMaxLno - 1
             << " lines, its instructions are not instrumented (see FileMapping.txt for the file)\n";
    }
    return 0;
  }
  return (static_cast<std::int64_t>(file_id) << kLidSize) + line;
}

// Encode the fileID and line number of BI as LID.
// Encode metadata regarding the instruction in the first LIDMETADATASIZE bits
// This is needed to support multiple files in a project.
std::int64_t GetLid(Instruction* bi, std::int32_t& file_id) {
  // prepare environment variables
  if (FileMappingPath().length() == 0) {
    const char* tmp = std::getenv("DOT_DISCOPOP");
    if (tmp == nullptr) {
      // DOT_DISCOPOP needs to be initialized
      setenv("DOT_DISCOPOP", ".discopop", 1);
    }
    FileMappingPath() = std::getenv("DOT_DISCOPOP");
    FileMappingPath() += "/FileMapping.txt";
  }

  std::int32_t lno = 0;

  const DebugLoc& location = bi->getDebugLoc();
  if (location) {
    lno = bi->getDebugLoc().getLine();
  } else if (isa<AllocaInst>(bi) || isa<StoreInst>(bi)) {
    lno = bi->getFunction()->getSubprogram()->getLine();
  } else {
    return 0;
  }

  if (file_id == 0) {
    // Get the new fileID.
    StringRef file = "", dir = "";
    MDNode* n = bi->getMetadata("dbg");
    if (n == nullptr) {
      // N == NULL means BI is only a helper instruction.
      // No metadata is attached to BI.
      return 0;
    }
    const DebugLoc& location = bi->getDebugLoc();
    const DILocation* loc = location.get();
    file = loc->getFilename();
    dir = loc->getDirectory();

    if (file.str().substr(0, 2) == "./") {
      const std::string sub = file.str().substr(0, 2);
      file = file.substr(2, file.size() - 1);
    }

    const std::string full_path_name = dir.str() + "/" + file.str();
    file_id = dputil::GetFileId(FileMappingPath(), full_path_name);

    // file is not in FileMapping.txt: there is no location to report. 0 means "no location" to every caller
    // (they do not instrument the instruction); -1 would have been instrumented as the location 262143:16383
    if (file_id == 0) {
      static std::set<std::string> warned_files;
      if (warned_files.insert(full_path_name).second) {
        errs() << "DiscoPoP: warning: " << full_path_name
               << " is not in the file mapping or outside of DP_PROJECT_ROOT_DIR, its instructions are not "
                  "instrumented\n";
      }
      return 0;
    }
  }
  return EncodeLid(file_id, lno);
}

// determine the file index according to the given FileMapping
void DetermineFileId(Function& f, std::int32_t& file_id) {
  // prepare environment variables
  if (FileMappingPath().length() == 0) {
    const char* tmp = std::getenv("DOT_DISCOPOP");
    if (tmp == nullptr) {
      // DOT_DISCOPOP needs to be initialized
      setenv("DOT_DISCOPOP", ".discopop", 1);
    }
    FileMappingPath() = std::getenv("DOT_DISCOPOP");
    FileMappingPath() += "/FileMapping.txt";
  }
  file_id = 0;

  for (Function::iterator fi = f.begin(), fe = f.end(); fi != fe; ++fi) {
    BasicBlock& bb = *fi;
    for (BasicBlock::iterator bi = bb.begin(), ei = bb.end(); bi != ei; ++bi) {
      std::int32_t lno;
      const DebugLoc& location = bi->getDebugLoc();
      if (location) {
        lno = bi->getDebugLoc().getLine();
      } else {
        lno = 0;
      }

      if (lno) {
        MDNode* n = bi->getMetadata("dbg");
        // N == NULL means BI is only a helper instruction.
        // No metadata is attached to BI.
        if (n) {
          StringRef file = "", dir = "";
          const DILocation* loc = location.get();
          file = loc->getFilename();
          dir = loc->getDirectory();

          char* absolute_path_file_name = realpath((dir.str() + "/" + file.str()).c_str(), nullptr);

          if (absolute_path_file_name == nullptr) {
            absolute_path_file_name = realpath(file.data(), nullptr);
          }

          if (absolute_path_file_name) {
            file_id = dputil::GetFileId(FileMappingPath(), std::string(absolute_path_file_name));
            std::free(absolute_path_file_name);  // allocated by realpath
          }
          // the first instruction with a debug location determines the file
          return;
        }
      }
    }
  }
}

std::string GetExeDir() {
  char buff[1024];
  const ssize_t len = ::readlink("/proc/self/exe", buff, sizeof(buff) - 1);
  if (len != -1) {
    buff[len] = '\0';
    const std::string full_path = std::string(buff);
    return full_path.substr(0, full_path.find_last_of('/'));
  }
  return "";
}

VariableNameFinder::VariableNameFinder(Module& /*M*/) {}

std::string VariableNameFinder::GetVarName(const Value* v) {
  if (const Instruction* i = dyn_cast<Instruction>(v)) {
    if (auto gepi = dyn_cast<GetElementPtrInst>(i)) {
      // an element (of an array, of a struct) is named like the object it belongs to
      return GetVarName(gepi->getOperand(0));
    }

    if (isa<SExtInst>(i)) {
      return GetVarName(i->getOperand(0));
    }

    if (const BinaryOperator* binop = dyn_cast<BinaryOperator>(i)) {
      std::string op;
      switch (binop->getOpcode()) {
#define DP_DPUTILS_DEBUG 1
        case Instruction::BinaryOps::Add:
          op = "+";
          break;
        case Instruction::BinaryOps::FAdd:
          op = "+";
          break;
        case Instruction::BinaryOps::Sub:
          op = "-";
          break;
        case Instruction::BinaryOps::FSub:
          op = "-";
          break;
        case Instruction::BinaryOps::Mul:
          op = "*";
          break;
        case Instruction::BinaryOps::FMul:
          op = "*";
          break;
        case Instruction::BinaryOps::UDiv:
          op = "/";
          break;
        case Instruction::BinaryOps::SDiv:
          op = "/";
          break;
        case Instruction::BinaryOps::FDiv:
          op = "/";
          break;
        case Instruction::BinaryOps::URem:
          op = "%";
          break;
        case Instruction::BinaryOps::SRem:
          op = "%";
          break;
        case Instruction::BinaryOps::FRem:
          op = "%";
          break;
        case Instruction::BinaryOps::Shl:
          op = "<<";
          break;
        case Instruction::BinaryOps::LShr:
          op = ">>";
          break;
        case Instruction::BinaryOps::AShr:
          op = ">>";
          break;
        case Instruction::BinaryOps::And:
          op = "&&";
          break;
        case Instruction::BinaryOps::Or:
          op = "||";
          break;
        case Instruction::BinaryOps::Xor:
          op = "^^";
          break;

          // robust solution to API changes (e.g. llvm adds more instruction
          // types) case Instruction::BinaryOps::BinaryOpsEnd: // fall through
        default:
#ifdef DP_DEBUG_TYPE
          errs() << "DPUTils VariableNameFinder::getVarName:  did not consider "
                    "enum value in switch on BinaryOperator";
#endif
          break;
      }
      return GetVarName(i->getOperand(0)) + op + GetVarName(i->getOperand(1));
    }

    if (isa<StoreInst>(i) || isa<LoadInst>(i)) {
      Value* v = i->getOperand((isa<StoreInst>(i) ? 1 : 0));
      if (isa<LoadInst>(v)) {
        return "*" + GetVarName(v);
      }
      return GetVarName(v);
    }
  }

  if (const GEPOperator* gepo = dyn_cast<GEPOperator>(v)) {
    if (const GlobalVariable* gv = dyn_cast<GlobalVariable>(gepo->getPointerOperand())) {
      if (isa<StructType>(gepo->getSourceElementType())) {
        return GlobalValue::getGlobalIdentifier(gv->getName(), gv->getLinkage(), gv->getParent()->getSourceFileName());
      }
    }
  }

  if (const ConstantInt* ci = dyn_cast<ConstantInt>(v)) {
    return std::to_string(ci->getSExtValue());
  }

  if (v->hasName()) {
    std::string r = v->getName().str();
    //    std::size_t found = r.find(".addr");
    //    if (found != string::npos) {
    //      return r.erase(found);
    //    }
    return r;
  }
  return "!";
}

}  // namespace dputil
