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
#include <omp.h>

typedef int32_t CALLPATH_STATE_ID;
typedef int32_t INSTRUCTION_ID;

std::unordered_map<StaticCalltreeNode*, std::unordered_set<CALLPATH_STATE_ID>> DiscoPoP::get_contained_in_map(std::unordered_map<CALLPATH_STATE_ID, std::vector<StaticCalltreeNode*>>& paths){
  std::unordered_map<StaticCalltreeNode*, std::unordered_set<CALLPATH_STATE_ID>> contained_in_map;
  for(auto pair: paths){
    for(auto node_ptr : pair.second){
      if(contained_in_map.find(node_ptr) == contained_in_map.end()){
        std::unordered_set<CALLPATH_STATE_ID> tmp;
        contained_in_map[node_ptr] = tmp;
      }
      contained_in_map[node_ptr].insert(pair.first);
    }
  }
  return contained_in_map;
}


string path_to_string(std::vector<StaticCalltreeNode*>& path){
  string path_str = "";
  for(auto elem: path){
    path_str += elem->get_label() + "-->";
  }
  return path_str;
}


// retrieve the CallpathStateId of the given path.
CALLPATH_STATE_ID get_id_from_callpath(std::vector<StaticCalltreeNode*>& target_path, std::unordered_map<CALLPATH_STATE_ID, std::vector<StaticCalltreeNode*>>& paths){
  CALLPATH_STATE_ID fallback = 0;
  std::size_t target_path_length = target_path.size();
  // fallback: search through all states
  for(auto pair: paths){
    if(pair.second.size() != target_path_length){
      continue;
    }
    // compare target path and the candidate element-wise
    bool valid = true;
    for(std::size_t idx = 0; idx < target_path_length; ++idx){
      if (target_path[idx] != pair.second[idx]){
        valid = false;
        break;
      }
    }
    // return the id, if a match was found
    if(valid){
      return pair.first;
    }
  }
  return fallback;
}

// retrieve the CallpathStateId of the given path.
CALLPATH_STATE_ID get_id_from_callpath_fast_old(std::vector<StaticCalltreeNode*>& target_path, std::unordered_map<CALLPATH_STATE_ID, std::vector<StaticCalltreeNode*>>& paths, std::unordered_map<StaticCalltreeNode*, std::unordered_set<int32_t>>& contained_in_map){
  std::size_t target_path_length = target_path.size();

  // try quicker search based on contained_in_map
  std::unordered_set<int32_t> candidates;
  bool candidates_initialized = false;
  cout << "Target path: " << path_to_string(target_path) << "\n";
  if(target_path_length>0){
    for(auto node_ptr: target_path){
      if(!candidates_initialized){
        candidates = contained_in_map[node_ptr];
        candidates_initialized = true;
        cout << "--> candidate size: " << candidates.size() << "\n";
        continue;
      }
      // remove non-overlapping entries from candidates
      std::unordered_set<int32_t>& current_set = contained_in_map[node_ptr];
      std::vector<int32_t> to_be_removed;
      for(auto state_id: candidates){
        if (auto iter = current_set.find(state_id); iter == current_set.end())
        // state_id not contained in currrent set, thus the candidate is invalid
          to_be_removed.push_back(state_id);
      }
      for(auto entry : to_be_removed){
        candidates.erase(entry);
      }
      cout << "--> candidate size: " << candidates.size() << "\n";
    }
    if(candidates.size() > 0){
      for(auto candidate_id: candidates){
        auto candidate_path = paths[candidate_id];
        cout << "  -> checking candidate: " << path_to_string(candidate_path) << "\n";

        if(candidate_path.size() != target_path_length){
          // ensure correct path length
          cout << "    -> incorrect size\n";
          continue;
        }

        bool valid = true;
        for(std::size_t idx = 0; idx < target_path_length; ++idx){
          if (target_path[idx] != candidate_path[idx]){
            valid = false;
            break;
          }
        }
        // return the id, if a match was found
        if(valid){
          return candidate_id;
        }
      }
      cout << "NO MATCH IN CANDIDATES\n";
    }
    else{
      cout << "NO CANDIDATES\n";
    }


  }

    // fallback, regular search
  return get_id_from_callpath(target_path, paths);
}



std::unordered_map<std::vector<StaticCalltreeNode*>, CALLPATH_STATE_ID, DiscoPoP::container_hash<std::vector<StaticCalltreeNode*>>> DiscoPoP::get_path_to_id_map(std::unordered_map<CALLPATH_STATE_ID, std::vector<StaticCalltreeNode*>>& paths){
  std::unordered_map<std::vector<StaticCalltreeNode*>, CALLPATH_STATE_ID, DiscoPoP::container_hash<std::vector<StaticCalltreeNode*>>> map;
  for(auto pair: paths){
    map[pair.second] = pair.first;
  }
  return map;
}


CALLPATH_STATE_ID get_id_from_callpath_fast(std::vector<StaticCalltreeNode*>& target_path, std::unordered_map<CALLPATH_STATE_ID, std::vector<StaticCalltreeNode*>>& paths, std::unordered_map<std::vector<StaticCalltreeNode*>, int32_t, DiscoPoP::container_hash<std::vector<StaticCalltreeNode*>>>& path_to_id_map){
  auto pos = path_to_id_map.find(target_path);
  if(pos != path_to_id_map.end()){
    return pos->second;
  }

  // fallback, regular search
  return get_id_from_callpath(target_path, paths);
}

void process_enumerate_paths_stack(std::atomic<short unsigned int> *active_threads, StaticCallPathTree* call_path_tree, std::stack<std::tuple<StaticCallPathTreeNode*, INSTRUCTION_ID, StaticCallPathTreeNode*>> *new_stack, std::mutex *new_stack_mtx){
  bool initial_iteration = true;
  std::vector<StaticCallPathTreeNode*> nodes_added_by_thread;
  while(active_threads->load() != 0){
    // at least one thread is not finished

    if(initial_iteration){
      // thread is already active
      initial_iteration = false;
    }
    else{
      // mark this thread as active
      active_threads->fetch_add(1);
    }

    while(!new_stack->empty()){
      // try fetch tuple
      std::tuple<StaticCallPathTreeNode*, INSTRUCTION_ID, StaticCallPathTreeNode*> new_current_tuple;
      bool fetched_element = false;
      {
        std::lock_guard<std::mutex> lg(*new_stack_mtx);
        if(!new_stack->empty()){
          new_current_tuple = new_stack->top();
          new_stack->pop();
          fetched_element = true;
        }
      }

      if(!fetched_element){
        // no element fetched. try again.
        break;
      }

      // successfully fetched element. process.

      auto predecessor_path = std::get<0>(new_current_tuple);
      auto transition_instruction = std::get<1>(new_current_tuple);
      auto new_current_path = std::get<2>(new_current_tuple);

      // register current path
      auto current_state_id = new_current_path->path_id;
      // register transition
      predecessor_path->register_transition(transition_instruction, current_state_id);

      // enqueue successors
      std::vector<std::tuple<StaticCallPathTreeNode*, int32_t, StaticCallPathTreeNode*>> new_elements_buffer;

      // The ancestor chain of new_current_path is identical for every successor,
      // so map base_node -> closest ancestor path node once, then look up per successor.
      std::unordered_map<StaticCalltreeNode*, StaticCallPathTreeNode*> ancestor_by_base;
      for(StaticCallPathTreeNode* current = new_current_path; current->base_node != nullptr; current = current->prefix){
        // keep the first (closest to new_current_path) match
        ancestor_by_base.emplace(current->base_node, current);
      }

      for(auto succ_pair: new_current_path->base_node->successors){
        int32_t trigger_instructionID = succ_pair.first;
        for(auto succ: succ_pair.second){

          // check for cycles: succ already present on the path -> cycle
          auto cycle_it = ancestor_by_base.find(succ);
          if(cycle_it != ancestor_by_base.end()){
            // register transition
            new_current_path->register_transition(trigger_instructionID, cycle_it->second->path_id);
            continue;
          }
          // new stack element
          auto new_path = new_current_path->get_or_register_successor(call_path_tree, succ);
          nodes_added_by_thread.push_back(new_path);
          new_elements_buffer.push_back(std::make_tuple(new_current_path, trigger_instructionID, new_path));

        }
      }
      // push prepared elements to stack
      {
        std::lock_guard<std::mutex> lg(*new_stack_mtx);
        for(auto elem : new_elements_buffer){
          new_stack->push(elem);
        }
      }
    }

    // mark thread as finished
    active_threads->fetch_sub(1);
    usleep(100);
  }

  // register nodes added by the thread for later use
  {
    std::lock_guard<std::mutex> lg(call_path_tree->all_nodes_mtx);
    for(auto elem : nodes_added_by_thread){
      call_path_tree->register_node_in_all_nodes(elem);
    }
  }

}

// create a complete list of callpaths and intermediate states based on the static call tree of the module
// and assign unique identifiers to every state
StaticCallPathTree* DiscoPoP::enumerate_paths(StaticCalltree& calltree, std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>> *state_transitions, std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>> *inverse_state_transitions, std::uint32_t start_path_id){
  // start ids from start_path_id (no collisions between modules)
  StaticCallPathTree* call_path_tree = new StaticCallPathTree(start_path_id);

  // path id 0 is reserved for debugging and initialization purposes
  // select entry nodes
  std::vector<StaticCalltreeNode*> entry_nodes;
  for(auto pair: calltree.function_map){
    if(pair.second->predecessors.size() == 0){
      entry_nodes.push_back(pair.second);
    }
    else{
      // ensure, that main is always an entry state
      if(pair.first == "main"){
        entry_nodes.push_back(pair.second);
      }
    }
  }
  // traverse the static calltree to build the paths
  std::stack<std::tuple<StaticCallPathTreeNode*, INSTRUCTION_ID, StaticCallPathTreeNode*>> new_stack;
  // -> initialize
  for(auto node_ptr: entry_nodes){
    // new stack
    auto new_node = call_path_tree->root->get_or_register_successor(call_path_tree, node_ptr);
    new_stack.push(std::make_tuple(call_path_tree->root, 0, new_node));
    call_path_tree->register_node_in_all_nodes(new_node);
  }
  // -> process stack concurrently

  unsigned int worker_count = 1; // std::thread::hardware_concurrency();
  if(worker_count == 0){
    worker_count = 1; // fallback, if concurrency could not be determined.
  }
  std::atomic<short unsigned int> active_threads(worker_count);
  std::mutex new_stack_mtx;
  std::mutex state_transitions_mtx;
  std::mutex inverse_state_transitions_mtx;

  std::vector<std::thread> workers;
  for(unsigned int i = 0; i < worker_count; ++i){
    workers.push_back(std::thread(process_enumerate_paths_stack, &active_threads, call_path_tree, &new_stack, &new_stack_mtx));
  }

  // join workers, wait for enumeration to be finished
  for(auto &worker: workers){
    worker.join();
  }

  return call_path_tree;
}

// save the id of the initial state id to file
void DiscoPoP::save_initial_path(StaticCallPathTree* call_path_tree_ptr){
  cout << "saving initial path..\n";

  // prepare saving the initial callpathStateID
  std::ofstream *file;
  file = new std::ofstream();
  std::string tmp01(getenv("DOT_DISCOPOP_PROFILER"));
  tmp01 += "/initial_stateID.txt";
  file->open(tmp01.data(), std::ios_base::app);

  // find candidates for initial path
  std::vector<StaticCallPathTreeNode*> candidates = call_path_tree_ptr->root->successors;

  // write file
  for(auto candidate: candidates){

    auto label = candidate->base_node->get_label();
    if (label.find("main") != std::string::npos)
    {
      cout << "CANDIDATE: " << label << "\n";
      // save path id to file
      *file << to_string(candidate->path_id) << "\n";
      cout << "FOUND A MAIN PATH!\n";
      break;
    }
  }
  // close file handle
  if (file != NULL && file->is_open()) {
    file->flush();
    file->close();
  }
  cout << "Done saving initial path..\n";
}

void DiscoPoP::save_enumerated_paths(StaticCallPathTree* call_path_tree_ptr){
  cout << "saving enumerated paths..\n";
  // prepare saving the mapping from callpath to callpathStateID for reference
  auto stateID_to_callpath_file = new std::ofstream();
  std::string tmp01(getenv("DOT_DISCOPOP_PROFILER"));
  tmp01 += "/stateID_to_callpath_mapping.txt";
  stateID_to_callpath_file->open(tmp01.data(), std::ios_base::app);
  // write file
  std::string global_buffer = "";
  #pragma omp parallel for reduction(+:global_buffer)
  for(auto path: call_path_tree_ptr->all_nodes){
/*
    Note: 12.02.2026: removing the states leads to holes in the data dependency information.
    These states could allow the detection of dependencies originating from the function argument initialization.

    // filter out paths ending with call instructions
    if(path->base_node != nullptr){
      if(path->base_node->get_type() == 1){
        // type is call instruction
        continue;
      }
    }
*/
    // root node uses itself as parent
    uint32_t parent_id = path->path_id;
    if(path->prefix != nullptr) {
        parent_id = path->prefix->path_id;
    }
    
    std::string node_label = "ROOT";
    if(path->base_node != nullptr) {
        node_label = path->base_node->get_label();
    }

    // new format: <NodeID> <ParentID> <Label>
    std::string path_buffer = std::to_string(path->path_id) + " " + std::to_string(parent_id) + " " + node_label + "\n";
    global_buffer += path_buffer;
  }
  *stateID_to_callpath_file << global_buffer;
  // close file handle
  if (stateID_to_callpath_file != NULL && stateID_to_callpath_file->is_open()) {
    stateID_to_callpath_file->flush();
    stateID_to_callpath_file->close();
  }
  cout << "Done saving enumerated path..\n";
}

void DiscoPoP::save_path_state_transitions(StaticCallPathTree* call_path_tree_ptr){
  cout << "saving path state transitions..\n";
  // prepare saving the callpathState transitions
  callpath_state_transitions_file = new std::ofstream();
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  tmp += "/callpath_state_transitions.txt";
  callpath_state_transitions_file->open(tmp.data(), std::ios_base::app);
  // write file
  *callpath_state_transitions_file << "# Format: <source_state_id> <instruction_id> <target_state_id>\n";

  std::string global_buffer = "";
  std::string return_targets_buffer = "# Format: <source_state_id> <target_state_id>\n";
  #pragma omp parallel for reduction(+:global_buffer)
  for(auto path: call_path_tree_ptr->all_nodes){
    for(auto transition_pair: path->state_transitions){
      if(transition_pair.first == 1){
        continue;
      }
      std::string transition_buffer = "" + std::to_string(path->path_id) + " " + std::to_string(transition_pair.first) + " " + std::to_string(transition_pair.second) + "\n";
      global_buffer += transition_buffer;
    }
  }
  for(auto path: call_path_tree_ptr->all_nodes){
    for(auto transition_pair: path->state_transitions){
      if(transition_pair.first == 1){
        return_targets_buffer += std::to_string(path->path_id) + " " + std::to_string(transition_pair.second) + "\n";
      }
    }
  }
  *callpath_state_transitions_file << global_buffer;
  // close file handle
  if (callpath_state_transitions_file != NULL && callpath_state_transitions_file->is_open()) {
    callpath_state_transitions_file->flush();
    callpath_state_transitions_file->close();
  }

  auto callpath_state_return_targets_file = new std::ofstream();
  std::string tmp03(getenv("DOT_DISCOPOP_PROFILER"));
  tmp03 += "/callpath_state_return_targets.txt";
  callpath_state_return_targets_file->open(tmp03.data(), std::ios_base::app);
  *callpath_state_return_targets_file << return_targets_buffer;
  if (callpath_state_return_targets_file != NULL && callpath_state_return_targets_file->is_open()) {
    callpath_state_return_targets_file->flush();
    callpath_state_return_targets_file->close();
  }

  // prepare saving the callpathState transitions as DOT file
  callpath_state_transitions_file = new std::ofstream();
  std::string tmp02(getenv("DOT_DISCOPOP_PROFILER"));
  tmp02 += "/callpath_state_transitions.dot";
  callpath_state_transitions_file->open(tmp02.data(), std::ios_base::app);
  // write file
  *callpath_state_transitions_file << "diGraph G {\n";

  global_buffer = "";  // reuse old global buffer
  #pragma omp parallel for reduction(+:global_buffer)
  for(auto path : call_path_tree_ptr->all_nodes){
    for(auto transition_pair: path->state_transitions){
      if(transition_pair.first == 1){
        continue;
      }
      std::string transition_buffer = "  " + std::to_string(path->path_id) + " -> " + std::to_string(transition_pair.second) + " [label = " + std::to_string(transition_pair.first) + "];\n";
      global_buffer += transition_buffer;
    }
  }
  *callpath_state_transitions_file << global_buffer;

  *callpath_state_transitions_file << "}\n";
  // close file handle
  if (callpath_state_transitions_file != NULL && callpath_state_transitions_file->is_open()) {
    callpath_state_transitions_file->flush();
    callpath_state_transitions_file->close();
  }
  cout << "Done saving path state transitions..\n";
}

void DiscoPoP::save_static_calltree_to_dot(StaticCalltree *calltree){
  cout << "saving path state transitions to dot..\n";
  std::ofstream *calltree_dot_file;
  // prepare saving the calltree as DOT file
  calltree_dot_file = new std::ofstream();
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  tmp += "/static_calltree.dot";
  calltree_dot_file->open(tmp.data(), std::ios_base::app);
  // write file
  *calltree_dot_file << calltree->to_dot_string() << "\n";

  // close file handle
  if (calltree_dot_file != NULL && calltree_dot_file->is_open()) {
    calltree_dot_file->flush();
    calltree_dot_file->close();
  }
  cout << "Done saving path state transitions to dot..\n";
}

// adds the state transition edges corresponding to returning from a function.
// for completeness and fail-safety, this edge is added to every state in a function, i.e., returning is possible from every state
void DiscoPoP::add_function_exit_edges_to_transitions(StaticCallPathTree* call_path_tree_ptr){

  // for each path in paths
    // rfind first call instruction
    // create prefix path, ending just before found call instruction
    // find state id for the prefix path
    // register edge transition from path to prefix path with trigger instruction "1" (i.e. leaving function)
  for(auto path: call_path_tree_ptr->all_nodes){
    auto path_id = path->path_id;
    // rfind first call instruction

    StaticCallPathTreeNode* last_call_prefix = nullptr;
    auto current = path;
    while(current->base_node != nullptr){
      if(current->base_node->get_type() == true){
        // base node is a call instruction
        last_call_prefix = current->prefix;
        break;
      }
      else{
        current = current->prefix;
      }
    }
    if(last_call_prefix == nullptr){
      // no call found
      continue;
    }

    // find state id for prefix path
    auto prefix_path_stateID = last_call_prefix->path_id;

    // register transition edge from path to prefix path with trigger instruction "1" (i.e. leaving function)
    path->register_transition(1, prefix_path_stateID);
  }
}
