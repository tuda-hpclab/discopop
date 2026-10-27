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

#include <string>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::DebugLoc;
using llvm::DISubprogram;
using llvm::dyn_cast;
using llvm::errs;
using llvm::Function;
using llvm::FunctionAnalysisManagerModuleProxy;
using llvm::MDNode;
using llvm::ModuleAnalysisManager;
using llvm::raw_string_ostream;
using llvm::Region;
using llvm::SmallVector;
using llvm::StringRef;

// Returns true if runOnFunction instruments F, i.e. F reports its entry and exit to the runtime.
// Calls to functions without instrumentation must not update the callpath state (see
// runOnBasicBlock): the runtime would wait for the callee's __dp_func_exit forever.
bool DiscoPoP::IsInstrumentedFunction(Function& f) {
  if (f.isDeclaration()) {
    return false;
  }

  const std::string dp_project_dir(dputil::GetEnvOrDefault("DP_PROJECT_ROOT_DIR", "/"));

  SmallVector<std::pair<unsigned, MDNode*>, 4> mds;
  f.getAllMetadata(mds);
  bool func_defined_in_project = false;
  for (auto& md : mds) {
    if (MDNode* n = md.second) {
      if (auto* sub_program = dyn_cast<DISubprogram>(n)) {
        std::string full_file_name = "";
        if (sub_program->getDirectory().str().length() > 0) {
          full_file_name += sub_program->getDirectory().str();
          full_file_name += "/";
        }
        full_file_name += sub_program->getFilename().str();
        if (full_file_name.find(dp_project_dir) != std::string::npos) {  // function defined inside project
          func_defined_in_project = true;
        }
      }
    }
  }
  if (!func_defined_in_project) {
    return false;
  }

  StringRef func_name = f.getName();
  // Avoid functions we don't want to instrument
  if (func_name.find("llvm.") != std::string::npos) {  // llvm debug calls
    return false;
  }
  if (func_name.find("__dp_") != std::string::npos) {  // instrumentation calls
    return false;
  }
  if (func_name.find("__cx") != std::string::npos) {  // c++ init calls
    return false;
  }
  if (func_name.find("__clang") != std::string::npos) {  // clang helper calls
    return false;
  }
  if (func_name.find("_GLOBAL_") != std::string::npos) {  // global init calls (c++)
    return false;
  }
  if (func_name.find("pthread_") != std::string::npos) {
    return false;
  }

  return GetCachedFileId(f) != 0;
}

std::int32_t DiscoPoP::GetCachedFileId(Function& f) {
  auto pos = file_id_cache.find(&f);
  if (pos != file_id_cache.end()) {
    return pos->second;
  }
  std::int32_t file_id = 0;
  dputil::DetermineFileId(f, file_id);
  file_id_cache[&f] = file_id;
  return file_id;
}

// The pass processes a function in four stages, in this order. None of them can run on its own,
// or for all functions before the next one starts:
//  1. buildCUGraph: the CU graph of the uninstrumented function (the calls inserted later would
//     split its CUs). It renames the unnamed basic blocks to CU ids, which CFA reads.
//  2. instrumentFunction: CFA needs the ids of the loop nodes of the CU graph. Inserts the
//     callbacks and assigns the instruction ids (dp.md.instr.id) in one walk over the function;
//     the loop and function entry calls are inserted before it, so they get ids, too.
//  3. writeCUGraph: Data.xml names the instruction ids of the calls.
//  4. the hybrid analysis: needs the instruction ids and the inserted access callbacks (it erases
//     those of the accesses it predicts statically). Its own instructions are inserted after the
//     walk, so they get no ids.
// State kept across functions makes the order of the functions matter as well:
// trueVarNamesFromMetadataMap grows per function (and the hybrid analysis adds an empty name for
// locals without a debug record, which later functions then use), so does
// programGlobalVariablesSet, and the loop ids are assigned in this order. No stage changes the
// control flow graph, so the analyses taken from MAM (LoopInfo, RegionInfo, DominatorTree) stay
// valid and are never invalidated; the reduction pass relies on getting the same llvm::Loop
// objects, as its loop ids are registered per llvm::Loop.
bool DiscoPoP::RunOnFunction(Function& f, ModuleAnalysisManager& mam) {
  if (kDpDebug) {
    errs() << "pass DiscoPoP: run pass on function " << f.getName().str() << "\n";
  }

  // avoid instrumenting functions which are defined outside the scope of the
  // project, as well as helper and instrumentation functions
  if (!IsInstrumentedFunction(f)) {
    return false;
  }

  FunctionCUGraph graph;
  // Created before fileID is set below: the ID of the function node holds the file id of the
  // function processed before (0 for the first one), as it always did in Data.xml.
  graph.root = new Node;

  file_id = GetCachedFileId(f);

  // only instrument functions belonging to project source files
  if (!file_id) {
    return false;
  }

  BuildCuGraph(f, mam, graph);
  InstrumentFunction(f, mam, graph);
  WriteCuGraph(graph);
  return hybrid_analysis_->AnalyzeFunction(f, mam, inserted_access_callbacks_, true_var_names_from_metadata_map_);
}

// CUGeneration
void DiscoPoP::BuildCuGraph(Function& f, ModuleAnalysisManager& mam, FunctionCUGraph& graph) {
  /********************* Initialize root values ***************************/
  graph.root->name = f.getName().str();
  graph.root->type = NodeTypes::kFunc;

  // Get list of arguments for this function and store them in root.
  // NOTE: changed the way we get the arguments
  BasicBlock* bb = &f.getEntryBlock();
  auto bi = bb->begin();
  std::string lid;
  if (DebugLoc dl = bi->getDebugLoc()) {
    lid = std::to_string(dl->getLine());
  } else {
    lid = std::to_string(bi->getFunction()->getSubprogram()->getLine());
  }

  for (Function::arg_iterator it = f.arg_begin(); it != f.arg_end(); it++) {
    std::string type_str;
    raw_string_ostream rso(type_str);
    (it->getType())->print(rso);
    const Variable v(it->getName().str(), rso.str(), std::to_string(file_id) + ":" + lid, true, true);
    graph.root->arguments_list.push_back(v);
  }
  /********************* End of initialize root values
   * ***************************/

  llvm::FunctionAnalysisManager& fam = mam.getResult<FunctionAnalysisManagerModuleProxy>(*this_module_).getManager();
  llvm::LoopInfo& li = fam.getResult<llvm::LoopAnalysis>(f);
  // LoopInfo &LI = getAnalysis<LoopInfoWrapperPass>(F).getLoopInfo();

  // get the top level region

  // RIpass = &getAnalysis<RegionInfoPass>(F);
  // RI = &(RIpass->getRegionInfo());
  // RegionInfoPass *RIpass;
  const llvm::RegionInfo& ri = fam.getResult<llvm::RegionInfoAnalysis>(f);

  Region* top_region = ri.getTopLevelRegion();

  GetTrueVarNamesFromMetadata(top_region, graph.root, &true_var_names_from_metadata_map_);

  GetFunctionReturnLines(top_region, graph.root);

  PopulateGlobalVariablesSet(top_region, graph.global_variables);

  CreateCus(top_region, graph.global_variables, graph.cus, graph.bb_id_to_cus, graph.root, li, mam);

  // inserts calls, but only after createCUs has seen the function without them
  if (DP_BRANCH_TRACKING) {
    CreateTakenBranchInstrumentation(top_region, graph.bb_id_to_cus);
  }

  FillCuVariables(top_region, graph.global_variables, graph.cus, graph.bb_id_to_cus);

  FillStartEndLineNumbers(graph.root, li, graph.loop_to_pet_node_id);

  // printOriginalVariables(originalVariablesSet);

  /*printData(root);

  for (auto i : CUVector) {
    delete (i);
  }*/
}
// CUGeneration end

// DPInstrumentation
void DiscoPoP::InstrumentFunction(Function& f, ModuleAnalysisManager& mam, const FunctionCUGraph& graph) {
  // Check loop parallelism?
  if (kClCheckLoopPar) {
    llvm::FunctionAnalysisManager& fam = mam.getResult<FunctionAnalysisManagerModuleProxy>(*this_module_).getManager();
    llvm::LoopInfo& li = fam.getResult<llvm::LoopAnalysis>(f);
    // LoopInfo &LI = getAnalysis<LoopInfoWrapperPass>(F).getLoopInfo();
    CFA(f, li, graph.loop_to_pet_node_id);
  }

  // Instrument the entry of the function.
  // Each function entry is instrumented, and the first
  // executed function will initialize shadow memory.
  // See the definition of __dp_func_entry() for detail.
  InstrumentFuncEntry(f);

  // Traverse all instructions, collect loads/stores/returns, check for calls.
  inserted_access_callbacks_.clear();
  for (Function::iterator fi = f.begin(), fe = f.end(); fi != fe; ++fi) {
    BasicBlock& bb = *fi;
    RunOnBasicBlock(bb);
  }

  if (kDpDebug) {
    errs() << "pass DiscoPoP: finished function\n";
  }
}
// DPInstrumentation end

// Print CU Graph
void DiscoPoP::WriteCuGraph(FunctionCUGraph& graph) {
  cu_output::WriteCuGraph(graph.root, loop_start_lines_);

  for (auto i : graph.cus) {
    delete (i);
  }
}
// Print CU Graph end
