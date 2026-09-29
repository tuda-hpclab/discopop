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
#include <unordered_set>

typedef int8_t TRANSITION_TYPE; // 0 -> enterLoop, 1 -> exitLoop, 2 -> incrementLoop
#define TRANSITION_TYPE_ENTERLOOP 0
#define TRANSITION_TYPE_EXITLOOP 1
#define TRANSITION_TYPE_INCREMENTLOOP 2

typedef int32_t LOOP_ID;
typedef std::vector<int32_t> ITERATION_INSTANCE;

// returns a mapping from loop id to the instruction id of the loop entry call
std::unordered_map<int32_t, int32_t> get_loop_entry_instructionIDs(Function &F){
  std::unordered_map<int32_t, int32_t> loop_entry_instruction_ids;
  for (Function::iterator FI = F.begin(), FE = F.end(); FI != FE; ++FI) {
    BasicBlock &BB = *FI;
    for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
      auto instruction = &*BI;
      if(isa<CallInst>(instruction)){
        auto ci = cast<CallInst>(BI);
        Function* F = ci->getCalledFunction();
        if(F){
          auto fn = F->getName();
          if (fn.find("__dp_loop_entry") != string::npos)
          {
            // get id of entered loop
            if (llvm::ConstantInt* CI = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(1))) {
              // operand is a ConstantInt, we can use CI here
              int32_t loop_id;
              if (CI->getBitWidth() <= 32) {
                loop_id = CI->getSExtValue();
              }

              // Get InstructionID of callinstruction
              MDNode* md = BI->getMetadata("dp.md.instr.id");
              if(md){
                // Metadata exists
                std::string callInstructionID_str = cast<MDString>(md->getOperand(0))->getString().str();
                callInstructionID_str.erase(0, 15);
                int32_t callInstructionID = stoi(callInstructionID_str);
                loop_entry_instruction_ids[loop_id] = callInstructionID;
              }
            }
            else {
              // operand was not a ConstantInt
            }
          }
        }
      }
    }
  }

  return loop_entry_instruction_ids;
}

// returns a mapping from loop id to the instruction id of the loop exit call
std::unordered_map<int32_t, int32_t> get_loop_exit_instructionIDs(Function &F){
  std::unordered_map<int32_t, int32_t> loop_exit_instruction_ids;
  for (Function::iterator FI = F.begin(), FE = F.end(); FI != FE; ++FI) {
    BasicBlock &BB = *FI;
    for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
      auto instruction = &*BI;
      if(isa<CallInst>(instruction)){
        auto ci = cast<CallInst>(BI);
        Function* F = ci->getCalledFunction();
        if(F){
          auto fn = F->getName();
          if (fn.find("__dp_loop_exit") != string::npos)
          {
            // get id of exited loop
            if (llvm::ConstantInt* CI = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(1))) {
              // operand is a ConstantInt, we can use CI here
              int32_t loop_id;
              if (CI->getBitWidth() <= 32) {
                loop_id = CI->getSExtValue();
              }

              // Get InstructionID of callinstruction
              MDNode* md = BI->getMetadata("dp.md.instr.id");
              if(md){
                // Metadata exists
                std::string callInstructionID_str = cast<MDString>(md->getOperand(0))->getString().str();
                callInstructionID_str.erase(0, 15);
                int32_t callInstructionID = stoi(callInstructionID_str);
                loop_exit_instruction_ids[loop_id] = callInstructionID;
              }
            }
            else {
              // operand was not a ConstantInt
            }
          }
        }
      }
    }
  }

  return loop_exit_instruction_ids;
}

// returns a mapping from loop id to the instruction id of the loop increment call
std::unordered_map<int32_t, int32_t> get_loop_increment_instructionIDs(Function &F){
  std::unordered_map<int32_t, int32_t> loop_increment_instruction_ids;
  for (Function::iterator FI = F.begin(), FE = F.end(); FI != FE; ++FI) {
    BasicBlock &BB = *FI;
    for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
      auto instruction = &*BI;
      if(isa<CallInst>(instruction)){
        auto ci = cast<CallInst>(BI);
        Function* F = ci->getCalledFunction();
        if(F){
          auto fn = F->getName();
          if (fn.find("__dp_loop_incr") != string::npos)
          {
            // get id of incremented loop
            if (llvm::ConstantInt* CI = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(0))) {
              // operand is a ConstantInt, we can use CI here
              int32_t loop_id;
              if (CI->getBitWidth() <= 32) {
                loop_id = CI->getSExtValue();
              }

              // Get InstructionID of callinstruction
              MDNode* md = BI->getMetadata("dp.md.instr.id");
              if(md){
                // Metadata exists
                std::string callInstructionID_str = cast<MDString>(md->getOperand(0))->getString().str();
                callInstructionID_str.erase(0, 15);
                int32_t callInstructionID = stoi(callInstructionID_str);
                loop_increment_instruction_ids[loop_id] = callInstructionID;
              }
            }
            else {
              // operand was not a ConstantInt
            }
          }
        }
      }
    }
  }

  return loop_increment_instruction_ids;
}

// A single node in the reconstructed loop nesting tree/forest. Unlike a flat per-region
// list, this preserves the true parent/child relationship between loops, which is required
// to tell true ancestors (must be active together) apart from siblings (mutually exclusive,
// since only one of them can be executing at any given time).
struct LoopTreeNode {
  LOOP_ID loop_id;
  std::vector<LoopTreeNode*> children;
};

// Reconstructs the real loop nesting forest for the given function by scanning the
// __dp_loop_entry / __dp_loop_exit call sequence with a stack. Returns one LoopTreeNode*
// per top-level loop (multiple roots if the function contains several independent
// top-level loop nests in sequence).
std::vector<LoopTreeNode*> build_loop_forest(Function &F){
  std::vector<LoopTreeNode*> roots;
  std::vector<LoopTreeNode*> open_loops; // stack; back() == innermost currently open loop

  for (Function::iterator FI = F.begin(), FE = F.end(); FI != FE; ++FI) {
    BasicBlock &BB = *FI;
    for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
      auto instruction = &*BI;
      if(isa<CallInst>(instruction)){
        auto ci = cast<CallInst>(BI);
        Function* calledFunc = ci->getCalledFunction();
        if(calledFunc){
          auto fn = calledFunc->getName();
          if (fn.find("__dp_loop_entry") != string::npos)
          {
            // get id of entered loop
            if (llvm::ConstantInt* CI = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(1))) {
              // operand is a ConstantInt, we can use CI here
              LOOP_ID loop_id = 0;
              if (CI->getBitWidth() <= 32) {
                loop_id = CI->getSExtValue();
              }
              LoopTreeNode* node = new LoopTreeNode();
              node->loop_id = loop_id;
              if(open_loops.empty()){
                roots.push_back(node);
              }
              else{
                open_loops.back()->children.push_back(node);
              }
              open_loops.push_back(node);
            }
            else {
              // operand was not a ConstantInt
            }

          }
          else{
            if (fn.find("__dp_loop_exit") != string::npos)
            {
              if(!open_loops.empty()){
                open_loops.pop_back();
              }
            }
          }
        }
      }
    }
  }

  return roots;
}

// Frees the nodes allocated by build_loop_forest for a single tree.
void delete_loop_tree(LoopTreeNode* node){
  for(auto child : node->children){
    delete_loop_tree(child);
  }
  delete node;
}

// Assigns each loop tree node a stable position (offset) within the flat ITERATION_INSTANCE
// vector via pre-order traversal, and records the resulting loop_id sequence (used to map
// an offset back to its loop_id, e.g. for debug output and in buildStaticCalltree).
void flatten_loop_forest(LoopTreeNode* node, std::vector<LOOP_ID>& out_sequence, std::unordered_map<LoopTreeNode*, int32_t>& node_to_offset){
  node_to_offset[node] = static_cast<int32_t>(out_sequence.size());
  out_sequence.push_back(node->loop_id);
  for(auto child : node->children){
    flatten_loop_forest(child, out_sequence, node_to_offset);
  }
}

// converts an iteration instance to its string representation (one digit per loop position)
string iteration_instance_to_string(const ITERATION_INSTANCE& instance){
  string result;
  result.reserve(instance.size());
  for(auto v : instance){
    result += to_string(v);
  }
  return result;
}

// Recursively generates states and ENTER/EXIT/INCREMENT transitions for the subtree rooted
// at `node`. We only ever branch within `node`'s own subtree, so every generated state
// automatically keeps `node`'s sibling loops -- and everything nested inside them -- at '3'
// ("dont care"). This is exactly the condition required to avoid enumerating states that can
// never occur at runtime, such as being inside two different, non-nested loops at once: since
// siblings and their entire contained subtrees are never touched here, they simply cannot
// appear as "active" together with `node`.
//
// `incoming_instances`: the valid states representing "about to enter `node`", i.e. all of
// node's ancestors already carry a concrete iteration value (0/1/2) and node's own position
// as well as all descendant positions are still '3'.
void generate_states_for_node(
    LoopTreeNode* node,
    const std::vector<ITERATION_INSTANCE>& incoming_instances,
    std::unordered_map<LoopTreeNode*, int32_t>& node_to_offset,
    std::unordered_map<string, std::unordered_map<TRANSITION_TYPE, std::unordered_map<LOOP_ID, string>>>& transitions,
    bool is_top_level){

  int32_t offset = node_to_offset[node];
  LOOP_ID loop_id = node->loop_id;

  std::vector<ITERATION_INSTANCE> own_instances;
  own_instances.reserve(incoming_instances.size() * 3);

  for(const auto& parent_instance : incoming_instances){
    string parent_instance_str = iteration_instance_to_string(parent_instance);

    ITERATION_INSTANCE variants[3];
    string variant_strs[3];
    for(int v = 0; v < 3; ++v){
      variants[v] = parent_instance;
      variants[v][offset] = v;
      variant_strs[v] = iteration_instance_to_string(variants[v]);
      own_instances.push_back(variants[v]);
    }

    // ENTER: parent -> variant[0] (entering always starts at iteration bucket 0)
    if(is_top_level){
      transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP][loop_id] = variant_strs[0];
    }
    else{
      transitions[parent_instance_str][TRANSITION_TYPE_ENTERLOOP][loop_id] = variant_strs[0];
    }

    // EXIT: any iteration bucket can be exited, always returning to the (unchanged) parent state
    string exit_target = is_top_level ? "exit_points" : parent_instance_str;
    for(int v = 0; v < 3; ++v){
      transitions[variant_strs[v]][TRANSITION_TYPE_EXITLOOP][loop_id] = exit_target;
    }

    // INCREMENT: cycle 0 -> 1 -> 2 -> 0
    transitions[variant_strs[0]][TRANSITION_TYPE_INCREMENTLOOP][loop_id] = variant_strs[1];
    transitions[variant_strs[1]][TRANSITION_TYPE_INCREMENTLOOP][loop_id] = variant_strs[2];
    transitions[variant_strs[2]][TRANSITION_TYPE_INCREMENTLOOP][loop_id] = variant_strs[0];
  }

  for(auto child : node->children){
    generate_states_for_node(child, own_instances, node_to_offset, transitions, false);
  }
}

// returns all combinations of allowed loop iteration counters for the given loop nesting
// forest. Unlike a flat/chain-based enumeration (which would generate 3^N states for N loops
// total, including states that are impossible at runtime), this walks the real loop nesting
// tree and only ever branches within a single node's own subtree at a time. As a result, a
// node at depth d contributes 3^d states instead of 3^N, since its siblings (and everything
// nested inside them) are guaranteed to stay "dont care".
std::unordered_map<string, std::unordered_map<TRANSITION_TYPE, std::unordered_map<LOOP_ID, string>>> get_loop_iteration_instances_and_transitions(std::vector<LoopTreeNode*>& forest, int32_t loop_count, std::unordered_map<LoopTreeNode*, int32_t>& node_to_offset){
  std::unordered_map<string, std::unordered_map<TRANSITION_TYPE, std::unordered_map<LOOP_ID, string>>> loop_iteration_instance_transitions;

  ITERATION_INSTANCE root_instance(loop_count, 3);
  std::vector<ITERATION_INSTANCE> root_instances{root_instance};

  for(auto root : forest){
    generate_states_for_node(root, root_instances, node_to_offset, loop_iteration_instance_transitions, true);
  }

  return loop_iteration_instance_transitions;
}


// returns a map from loopID to a vector of callInstructionIDs contained in the loop
std::unordered_map<int32_t, std::vector<int32_t>> get_loop_callInstruction_affectance(Function &F){
  std::unordered_map<int32_t, std::vector<int32_t>> result_map;

  std::vector<int32_t> entered_loops;

  for (Function::iterator FI = F.begin(), FE = F.end(); FI != FE; ++FI) {
    BasicBlock &BB = *FI;
    for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
      auto instruction = &*BI;
      // modify entered loops if required
      if(isa<CallInst>(instruction)){
        auto ci = cast<CallInst>(BI);
        Function* F = ci->getCalledFunction();
        if(F){
          auto fn = F->getName();
          if (fn.find("__dp_loop_entry") != string::npos)
          {
            // get id of entered loop
            if (llvm::ConstantInt* CI = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(1))) {
              // operand is a ConstantInt, we can use CI here
              int32_t loop_id;
              if (CI->getBitWidth() <= 32) {
                loop_id = CI->getSExtValue();
              }
              entered_loops.push_back(loop_id);
            }
            else {
              // operand was not a ConstantInt
            }
          }
          else{
            if (fn.find("__dp_loop_exit") != string::npos)
            {
              int32_t loop_id;
              // get id of entered loop
              if (llvm::ConstantInt* CI = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(1))) {
                // operand is a ConstantInt, we can use CI here
                if (CI->getBitWidth() <= 32) {
                  loop_id = CI->getSExtValue();
                }
                // Erase loop_id from entered loops
                for (auto it = entered_loops.begin(); it != entered_loops.end();)
                {
                    if (*it == loop_id)
                        it = entered_loops.erase(it);
                    else
                        ++it;
                }
              }
              else {
                // operand was not a ConstantInt
              }
            }
          }
        }
      }

      // register relation between loop and call instruction
      Function *F = nullptr;
      if(isa<CallInst>(BI)){
        F = (cast<CallInst>(BI))->getCalledFunction();
      }
      else if(isa<InvokeInst>(BI)){
        F = (cast<InvokeInst>(BI))->getCalledFunction();
      }
      // check if a call was encountered
      if (F) {
        // ignore instrumentation functions
        auto fn = F->getName();
        if (fn.find("__dp_") != string::npos)
        {
          continue;
        }
        if (fn.find("__clang_") != string::npos)
        {
          continue;
        }
        if (fn.find("llvm.dbg.declare") != string::npos)
        {
          continue;
        }
        // Get InstructionID of callinstruction
        MDNode* md = BI->getMetadata("dp.md.instr.id");
        if(md){
          // Metadata exists
          std::string callInstructionID_str = cast<MDString>(md->getOperand(0))->getString().str();
          callInstructionID_str.erase(0, 15);
          int callInstructionID = stoi(callInstructionID_str);

          // extend map
          for(auto loop_id: entered_loops){
            if(result_map.count(loop_id) == 0){
              std::vector<int32_t> tmp;
              result_map[loop_id] = tmp;
            }
            result_map[loop_id].push_back(callInstructionID);
          }
        }
      }
    }
  }

  return result_map;
}

// inverts the given map. Returns a map from CallInstructionID to LoopIDs which affect it.
std::unordered_map<int32_t, std::vector<int32_t>> get_inverted_loop_callInstruction_affectance(std::unordered_map<int32_t, std::vector<int32_t>> loop_call_affectance){
  std::unordered_map<int32_t, std::vector<int32_t>> result_map;
  for(auto pair: loop_call_affectance){
    auto loop_id = pair.first;
    for(auto call_inst_id: pair.second){
      if(result_map.count(call_inst_id) == 0){
        std::vector<int32_t> tmp;
        result_map[call_inst_id] = tmp;
      }
      result_map[call_inst_id].push_back(loop_id);
    }
  }

  return result_map;
}

// builds a call tree for the given Module on the basis of the statically available information
StaticCalltree DiscoPoP::buildStaticCalltree(Module &M) {
  StaticCalltree calltree;
  for (Function &F : M) {
    cout << "BUILDING FUNCTION: " << F.getName().str() << "\n";
    // reconstruct the real loop nesting tree (preserves parent/child relationships, which is
    // required to tell true ancestors apart from mutually-exclusive sibling loops)
    auto loop_forest = build_loop_forest(F);
    std::vector<LOOP_ID> sequentialized_contained_loops;
    std::unordered_map<LoopTreeNode*, int32_t> node_to_offset;
    for(auto root : loop_forest){
      flatten_loop_forest(root, sequentialized_contained_loops, node_to_offset);
    }
    //cerr << "seq_contained_loops: " << std::endl;
    //for (auto s : sequentialized_contained_loops){
    //  cerr << " --> " << s << std::endl;
    //}
    auto loop_entry_instructionIDs = get_loop_entry_instructionIDs(F);
    auto loop_exit_instructionIDs = get_loop_exit_instructionIDs(F);
    auto loop_increment_instructionIDs = get_loop_increment_instructionIDs(F);

    // for each loop, allow 3 values to represent the currently executed iteration
    // create one instance of the function_node in the calltree per combination of iterations.
    // The value 3 is chosen to keep the amount of total states somewhat concise, while still allowing to distinguish between
    // intra- and inter-iteration dependencies with a comparatively high probability.
    // Valid Iteration counters are 0, 1, and 2. A value of 3 acts as a "dont care" symbol.
    // Only states that respect the real loop nesting tree are generated: a loop's ancestors
    // must be active for it to be entered, and its siblings (and everything nested inside
    // them) always remain "dont care", since they cannot be active at the same time. This
    // bounds the number of states for a given loop by 3^depth instead of 3^(total loop count).
    auto iteration_instances_and_transitions = get_loop_iteration_instances_and_transitions(loop_forest, (int32_t)sequentialized_contained_loops.size(), node_to_offset);

    for(auto root : loop_forest){
      delete_loop_tree(root);
    }

    // create StaticCalltreeNode instances for function F
    std::vector<StaticCalltreeNode*> function_node_instances;

    StaticCalltreeNode* original_function_node_ptr = calltree.get_or_insert_function_node(F.getName().str());

    std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> loop_activity_map;
    std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> loop_entry_nodes_map;
    std::unordered_map<string, StaticCalltreeNode*> instance_to_node_map;
    for(auto pair: iteration_instances_and_transitions){
      auto instance = pair.first;

      // skip instance "entry_points"
      if (instance.find("entry_points") != string::npos)
      {
        continue;
      }

      StaticCalltreeNode* function_node_ptr = calltree.get_or_insert_function_node(F.getName().str(), instance);
      function_node_instances.push_back(function_node_ptr);
      instance_to_node_map[instance] = function_node_ptr;

      // register loop activity for later use (loop active, if iteration count != 3 (i.e. don't care))
      for(std::size_t idx = 0; idx < instance.size(); ++idx){
        int iteration_counter = instance[idx] - '0';
        if(iteration_counter != 3){
          // get loop id from position via lookup in sequentialized_contained_loops
          auto active_loop_id = sequentialized_contained_loops[idx];
          if(loop_activity_map.count(active_loop_id) == 0){
            std::vector<StaticCalltreeNode*> tmp;
            loop_activity_map[active_loop_id] = tmp;
          }
          loop_activity_map[active_loop_id].push_back(function_node_ptr);

          // check if the current instance is an entry node to the loop.
          // save for later use if so.
          if (iteration_instances_and_transitions.find("entry_points") != iteration_instances_and_transitions.end())
          {
            // "entry_points" is a key
            if (iteration_instances_and_transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP].find(active_loop_id) != iteration_instances_and_transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP].end())
            {
              // entry point for loop is registered
              if(iteration_instances_and_transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP][active_loop_id] == instance){
                // instance is an entry point to the loop
                if(loop_entry_nodes_map.find(active_loop_id) == loop_entry_nodes_map.end()){
                  std::vector<StaticCalltreeNode*> tmp;
                  loop_entry_nodes_map[active_loop_id] = tmp;
                }
                loop_entry_nodes_map[active_loop_id].push_back(function_node_ptr);
              }
            }
          }
        }

      }
    }


    // add entry edges into the loops
    if (iteration_instances_and_transitions.find("entry_points") != iteration_instances_and_transitions.end())
    {
      for(auto pair: iteration_instances_and_transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP]){
        auto loop_id = pair.first;
        auto loop_entry_instance = pair.second;
        calltree.addEdge(original_function_node_ptr, instance_to_node_map[loop_entry_instance], loop_entry_instructionIDs[loop_id]);
      }
    }

    // add transition edges between loop iteration nodes
    for(auto pair_0: iteration_instances_and_transitions){
      auto source_instance = pair_0.first;
      if (source_instance.find("entry_points") != string::npos){
        // ignore the "entry_points" key in the transition map
        continue;
      }
      for(auto pair_1: pair_0.second){
        auto transition_type = pair_1.first;
        for(auto pair_2: pair_1.second){
          auto loop_id = pair_2.first;
          auto target_instance = pair_2.second;
          // determine nodes
          auto source_node = instance_to_node_map[source_instance];
          StaticCalltreeNode* target_node = nullptr;
          if (target_instance.find("exit_points") != string::npos){
            // target is leaving a function scope, i.e. goes back to the function node
            target_node = original_function_node_ptr;
          }
          else{
            target_node = instance_to_node_map[target_instance];
          }

          // determine trigger instruction
          int32_t trigger_instruction = 0;
          if(transition_type == TRANSITION_TYPE_ENTERLOOP){
            trigger_instruction = loop_entry_instructionIDs[loop_id];
          }
          else if(transition_type == TRANSITION_TYPE_EXITLOOP){
            trigger_instruction = loop_exit_instructionIDs[loop_id];
          }
          else if(transition_type == TRANSITION_TYPE_INCREMENTLOOP){
            trigger_instruction = loop_increment_instructionIDs[loop_id];
            //cerr << "LOOP_ID: " << loop_id << std::endl;
            //cerr << "TRIGGER: " << trigger_instruction << std::endl;
          }
          // create edge
          calltree.addEdge(source_node, target_node, trigger_instruction);
        }
      }
    }


    // get connection between loops and called functions inside the loops
    auto loop_call_affectance = get_loop_callInstruction_affectance(F);
    auto inverted_loop_call_affectance = get_inverted_loop_callInstruction_affectance(loop_call_affectance);

    for (Function::iterator FI = F.begin(), FE = F.end(); FI != FE; ++FI) {
      BasicBlock &BB = *FI;
      for (BasicBlock::iterator BI = BB.begin(), E = BB.end(); BI != E; ++BI) {
        Function *F = nullptr;
        if(isa<CallInst>(BI)){
          F = (cast<CallInst>(BI))->getCalledFunction();
        }
        else if(isa<InvokeInst>(BI)){
          F = (cast<InvokeInst>(BI))->getCalledFunction();
        }
        // check if a call was encountered
        if (F) {
          // ignore instrumentation functions
          auto fn = F->getName();
          if (fn.find("__dp_") != string::npos)
          {
            continue;
          }
          if (fn.find("__clang_") != string::npos)
          {
            continue;
          }
          // ignore LLVM intrinsics (e.g. llvm.fmuladd.*, llvm.dbg.*, llvm.memcpy.*): these are
          // lowered arithmetic/metadata operations, not real calls, and have no call-graph meaning.
          if (F->isIntrinsic())
          {
            continue;
          }
          // register CallInstruction Node in StaticCalltree
          MDNode* md = BI->getMetadata("dp.md.instr.id");
          if(md){
            // Metadata exists
            std::string callInstructionID_str = cast<MDString>(md->getOperand(0))->getString().str();
            callInstructionID_str.erase(0, 15);
            int32_t callInstructionID = stoi(callInstructionID_str);
            StaticCalltreeNode* callInstructionNode_ptr = calltree.get_or_insert_instruction_node(callInstructionID);
            calltree.addEdge(original_function_node_ptr, callInstructionNode_ptr, callInstructionID);
            // connect to nodes if the loop contains the call and the loop is "active" and node is an entry node to the loop, i.e. iteration count is 0
            auto parent_loops = inverted_loop_call_affectance[callInstructionID];
            for(auto parent_loop_id : parent_loops){
              for(auto node_ptr: loop_activity_map[parent_loop_id]){
                calltree.addEdge(node_ptr, callInstructionNode_ptr, callInstructionID);
              }
            }
            StaticCalltreeNode* calleeNode_ptr = calltree.get_or_insert_function_node(F->getName().str());
            calltree.addEdge(callInstructionNode_ptr, calleeNode_ptr, 0);
          }
        }
      }
    }
  }
  return calltree;
}
