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

#include <iostream>
#include <thread>
#include <unordered_map>

#include "DiscoPoP.hpp"

using llvm::Function;
using llvm::Instruction;
using llvm::Loop;
using llvm::Module;
using llvm::ModuleAnalysisManager;

// pass get invoked here
bool DiscoPoP::RunOnModule(Module& m, ModuleAnalysisManager& mam) {
  std::cout << "MODULE " << m.getName().str() << "\n";

  DoInitialization(m);

  // prepare saving the mapping from instructionID to lineID for backwards compatibility
  instruction_id_to_line_id_lock = std::make_unique<profiler_files::FileLock>("instructionID_to_lineID_mapping.txt");
  instruction_id_to_line_id_file = profiler_files::Open("instructionID_to_lineID_mapping.txt");

  // cout << "\tFUNCTION:\n";
  for (Function& f : m) {
    /*
        string to_be_printed = "\t(" + to_string(++counter) + " / " +
       to_string(M.size()) + ") -- " + F.getName().str();
        while(to_be_printed.size() < 100){
            to_be_printed += " ";
        }
        cout << to_be_printed + "\r";
    */
    RunOnFunction(f, mam);
  }

  // DPReduction

  dp_reduction::ReductionInstrumenter reduction(
      m, {[this](Function& f) { return GetCachedFileId(f); }, [this](Loop* l) { return GetOrRegisterLoopId(l); },
          [this](Instruction* i) { return DpReductionDetermineVariableName(i, &true_var_names_from_metadata_map_); }});

  reduction.InstrumentModule(mam);

  reduction.InsertFunctions();

  // disambiguating instructions
  AssignInstructionIdsToDpReductionFunctions(m);
  // update argument instruction ids
  UpdateArgumentInstructionIds(m);
  // restore callpath states after exceptions (needs the function entry ids)
  InstrumentLandingPads(m);
  // prepare information for call state transitioning and instruction mapping during dynamic analysis.
  // -> build static calltree for state transition and instruction mapping preparation
  std::cout << "Building static calltree..\n";
  StaticCalltree static_calltree = static_callpaths::BuildStaticCalltree(m, loop_id_to_identity);
  std::cout << "Done building static calltree..\n";
  // -> assign unique stateIDs to all possible call states
  std::cout << "Enumerating paths..\n";
  auto start = std::chrono::high_resolution_clock::now();
  std::unordered_map<std::int32_t, std::unordered_map<std::int32_t, std::int32_t>> state_transitions;
  std::unordered_map<std::int32_t, std::unordered_map<std::int32_t, std::int32_t>> inverse_state_transitions;
  [[maybe_unused]] auto state_transitions_ptr = &state_transitions;
  [[maybe_unused]] auto inverset_state_transitions_ptr = &inverse_state_transitions;
  auto static_calltree_ptr = &static_calltree;
  auto call_path_tree_ptr = static_callpaths::EnumeratePaths(static_calltree, &state_transitions,
                                                             &inverse_state_transitions);
  auto end = std::chrono::high_resolution_clock::now();
  auto time = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
  std::cout << "Done enumerating paths.. took: " << (time / 1000.0) << "s" << std::endl;

  // DEBUG
  // std::cout << "CallPathTree: " << std::endl;
  // std::cout << call_path_tree_ptr->to_dot_string();
  // std::cout << "! CallPathTree " << std::endl;
  // !DEBUG

  // add fucntion exit edges to state_transitions
  std::cout << "START AFEETT..\n";
  // add_function_exit_edges_to_transitions(state_transitions, call_path_tree_ptr); // enumerated_paths,
  // path_to_id_map);
  static_callpaths::AddFunctionExitEdgesToTransitions(call_path_tree_ptr);  // enumerated_paths, path_to_id_map);
  std::cout << "Done AFEETT..\n";

  // save the generated paths and transitions to disk
  std::thread t1([call_path_tree_ptr]() { static_callpaths::SaveInitialPath(call_path_tree_ptr); });
  std::thread t2([call_path_tree_ptr]() { static_callpaths::SaveEnumeratedPaths(call_path_tree_ptr); });
  // std::thread t3([this, state_transitions_ptr](){this->save_path_state_transitions(state_transitions_ptr);});
  std::thread t3([call_path_tree_ptr]() { static_callpaths::SavePathStateTransitions(call_path_tree_ptr); });
  std::thread t4([static_calltree_ptr]() { static_callpaths::SaveStaticCalltreeToDot(static_calltree_ptr); });
  std::thread t5([call_path_tree_ptr]() { static_callpaths::SaveFunctionEntries(call_path_tree_ptr); });

  t1.join();
  t2.join();
  t3.join();
  t4.join();
  t5.join();

  // closing flushes
  instruction_id_to_line_id_file.close();
  instruction_id_to_line_id_lock.reset();
  reduction.Close();
  // End DPReduction

  DoFinalization(m);

  delete call_path_tree_ptr;

  return true;
}
