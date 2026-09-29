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
#include <thread>

// pass get invoked here
bool DiscoPoP::runOnModule(Module &M, ModuleAnalysisManager &MAM) {
  cout << "MODULE " << M.getName().str() << "\n";

  doInitialization(M);
  module_ = &M;
  ctx_ = &module_->getContext();

  // prepare saving the mapping from instructionID to lineID for backwards compatibility
  instructionID_to_lineID_file = new std::ofstream();
  std::string tmp0(getenv("DOT_DISCOPOP_PROFILER"));
  tmp0 += "/instructionID_to_lineID_mapping.txt";
  instructionID_to_lineID_file->open(tmp0.data(), std::ios_base::app);

  // cout << "\tFUNCTION:\n";
  for (Function &F : M) {
    /*
        string to_be_printed = "\t(" + to_string(++counter) + " / " +
       to_string(M.size()) + ") -- " + F.getName().str();
        while(to_be_printed.size() < 100){
            to_be_printed += " ";
        }
        cout << to_be_printed + "\r";
    */
    runOnFunction(F, MAM);
  }

  // DPReduction

  reduction_file = new std::ofstream();
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  tmp += "/reduction.txt";
  reduction_file->open(tmp.data(), std::ios_base::app);

  loop_counter_file = new std::ofstream();
  std::string tmp2(getenv("DOT_DISCOPOP_PROFILER"));
  tmp2 += "/loop_counter_output.txt";
  loop_counter_file->open(tmp2.data(), std::ios_base::app);

  /*
  bool success = dp_reduction_init_util(FileMappingPath);
  if (!success) {
      llvm::errs() << "could not find the FileMapping file: " << FileMappingPath
  << "\n"; return false;
  }
  */
  instrument_module(&M, &trueVarNamesFromMetadataMap, MAM);

  dp_reduction_insert_functions();

  // disambiguating instructions
  assign_instruction_ids_to_dp_reduction_functions(M);
  // update argument instruction ids
  update_argument_instruction_ids(M);
  // prepare information for call state transitioning and instruction mapping during dynamic analysis.
  // -> build static calltree for state transition and instruction mapping preparation
  cout << "Building static calltree..\n";
  StaticCalltree static_calltree = buildStaticCalltree(M);
  cout << "Done building static calltree..\n";
  // -> assign unique stateIDs to all possible call states
  cout << "Enumerating paths..\n";
  auto start = chrono::high_resolution_clock::now();
  std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>> state_transitions;
  std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>> inverse_state_transitions;
  auto state_transitions_ptr = &state_transitions;
  auto inverset_state_transitions_ptr = &inverse_state_transitions;
  auto static_calltree_ptr = &static_calltree;
  auto call_path_tree_ptr = enumerate_paths(static_calltree, &state_transitions, &inverse_state_transitions, unique_callpath_state_id);
  auto end = chrono::high_resolution_clock::now();
  auto time = std::chrono::duration_cast<std::chrono::milliseconds>(end-start).count();
  cout << "Done enumerating paths.. took: " << (time/1000.0) << "s" << std::endl;

  // DEBUG
  //std::cout << "CallPathTree: " << std::endl;
  //std::cout << call_path_tree_ptr->to_dot_string();
  //std::cout << "! CallPathTree " << std::endl;
  // !DEBUG


  // prepare quicker search
  //cout << "START prepare PITIM..\n";
  //auto contained_in_map = get_contained_in_map(enumerated_paths);

  // TODO REMOVE? - covered by new StaticCallPathTree
  //auto path_to_id_map = get_path_to_id_map(enumerated_paths);
  //cout << "DONE prepare PITIM..\n";


  // add fucntion exit edges to state_transitions
  cout << "START AFEETT..\n";
  //add_function_exit_edges_to_transitions(state_transitions, call_path_tree_ptr); // enumerated_paths, path_to_id_map);
  add_function_exit_edges_to_transitions(call_path_tree_ptr); // enumerated_paths, path_to_id_map);
  cout << "Done AFEETT..\n";


  // save the generated paths and transitions to disk
  std::thread t1([this, call_path_tree_ptr](){this->save_initial_path(call_path_tree_ptr);});
  std::thread t2([this, call_path_tree_ptr](){this->save_enumerated_paths(call_path_tree_ptr);});
  //std::thread t3([this, state_transitions_ptr](){this->save_path_state_transitions(state_transitions_ptr);});
  std::thread t3([this, call_path_tree_ptr](){this->save_path_state_transitions(call_path_tree_ptr);});
  std::thread t4([this, static_calltree_ptr](){this->save_static_calltree_to_dot(static_calltree_ptr);});

  t1.join();
  t2.join();
  t3.join();
  t4.join();


  // save current instructionID for continuation in the next Module
  InstructionIDCounter = unique_llvm_ir_instruction_id;

  // update the global path id so the next module starts with a new id
  unique_callpath_state_id = call_path_tree_ptr->get_current_free_path_id();

  // save current stateID for continuation in the next Module
  CallpathStateIDCounter = unique_callpath_state_id;

  if (instructionID_to_lineID_file != NULL && instructionID_to_lineID_file->is_open()) {
    instructionID_to_lineID_file->flush();
    instructionID_to_lineID_file->close();
  }

  if (reduction_file != NULL && reduction_file->is_open()) {
    reduction_file->flush();
    reduction_file->close();
  }

  if (loop_counter_file != NULL && loop_counter_file->is_open()) {
    loop_counter_file->flush();
    loop_counter_file->close();
  }
  // End DPReduction

  doFinalization(M);

  delete call_path_tree_ptr;

  return true;
}
