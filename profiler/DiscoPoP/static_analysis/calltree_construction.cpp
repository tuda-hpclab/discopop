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
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::CallInst;
using llvm::cast;
using llvm::DominatorTree;
using llvm::dyn_cast;
using llvm::Function;
using llvm::Instruction;
using llvm::InvokeInst;
using llvm::isa;
using llvm::Loop;
using llvm::LoopInfo;
using llvm::MDNode;
using llvm::MDString;
using llvm::Module;

using TransitionType = std::int8_t;  // 0 -> enterLoop, 1 -> exitLoop, 2 -> incrementLoop
#define TRANSITION_TYPE_ENTERLOOP 0
#define TRANSITION_TYPE_EXITLOOP 1
#define TRANSITION_TYPE_INCREMENTLOOP 2

using LoopId = std::int32_t;
using IterationInstance = std::vector<std::int32_t>;

// returns a mapping from loop id to the instruction id of the loop entry call
std::unordered_map<std::int32_t, std::int32_t> GetLoopEntryInstructionIds(Function& f) {
  std::unordered_map<std::int32_t, std::int32_t> loop_entry_instruction_ids;
  for (Function::iterator fi = f.begin(), fe = f.end(); fi != fe; ++fi) {
    BasicBlock& bb = *fi;
    for (BasicBlock::iterator bi = bb.begin(), e = bb.end(); bi != e; ++bi) {
      auto instruction = &*bi;
      if (isa<CallInst>(instruction)) {
        auto ci = cast<CallInst>(bi);
        Function* f = ci->getCalledFunction();
        if (f) {
          auto fn = f->getName();
          if (fn.find("__dp_loop_entry") != std::string::npos) {
            // get id of entered loop
            if (const llvm::ConstantInt* const_int = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(1))) {
              // operand is a ConstantInt, we can use CI here
              std::int32_t loop_id;
              if (const_int->getBitWidth() <= 32) {
                loop_id = const_int->getSExtValue();
              }

              // Get InstructionID of callinstruction
              MDNode* md = bi->getMetadata("dp.md.instr.id");
              if (md) {
                // Metadata exists
                std::string call_instruction_id_str = cast<MDString>(md->getOperand(0))->getString().str();
                call_instruction_id_str.erase(0, 15);
                std::int32_t call_instruction_id = std::stoi(call_instruction_id_str);
                loop_entry_instruction_ids[loop_id] = call_instruction_id;
              }
            } else {
              // operand was not a ConstantInt
            }
          }
        }
      }
    }
  }

  return loop_entry_instruction_ids;
}

// returns a mapping from loop id to the instruction ids of the loop's exit calls (one per real
// exit block, see CFA)
std::unordered_map<std::int32_t, std::vector<std::int32_t>> GetLoopExitInstructionIds(Function& f) {
  std::unordered_map<std::int32_t, std::vector<std::int32_t>> loop_exit_instruction_ids;
  for (Function::iterator fi = f.begin(), fe = f.end(); fi != fe; ++fi) {
    BasicBlock& bb = *fi;
    for (BasicBlock::iterator bi = bb.begin(), e = bb.end(); bi != e; ++bi) {
      auto instruction = &*bi;
      if (isa<CallInst>(instruction)) {
        auto ci = cast<CallInst>(bi);
        Function* f = ci->getCalledFunction();
        if (f) {
          auto fn = f->getName();
          if (fn.find("__dp_loop_exit") != std::string::npos) {
            // get id of exited loop
            if (const llvm::ConstantInt* const_int = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(1))) {
              // operand is a ConstantInt, we can use CI here
              std::int32_t loop_id;
              if (const_int->getBitWidth() <= 32) {
                loop_id = const_int->getSExtValue();
              }

              // Get InstructionID of callinstruction
              MDNode* md = bi->getMetadata("dp.md.instr.id");
              if (md) {
                // Metadata exists
                std::string call_instruction_id_str = cast<MDString>(md->getOperand(0))->getString().str();
                call_instruction_id_str.erase(0, 15);
                std::int32_t call_instruction_id = std::stoi(call_instruction_id_str);
                loop_exit_instruction_ids[loop_id].push_back(call_instruction_id);
              }
            } else {
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
std::unordered_map<std::int32_t, std::int32_t> GetLoopIncrementInstructionIds(Function& f) {
  std::unordered_map<std::int32_t, std::int32_t> loop_increment_instruction_ids;
  for (Function::iterator fi = f.begin(), fe = f.end(); fi != fe; ++fi) {
    BasicBlock& bb = *fi;
    for (BasicBlock::iterator bi = bb.begin(), e = bb.end(); bi != e; ++bi) {
      auto instruction = &*bi;
      if (isa<CallInst>(instruction)) {
        auto ci = cast<CallInst>(bi);
        Function* f = ci->getCalledFunction();
        if (f) {
          auto fn = f->getName();
          if (fn.find("__dp_loop_incr") != std::string::npos) {
            // get id of incremented loop
            if (const llvm::ConstantInt* const_int = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(0))) {
              // operand is a ConstantInt, we can use CI here
              std::int32_t loop_id;
              if (const_int->getBitWidth() <= 32) {
                loop_id = const_int->getSExtValue();
              }

              // Get InstructionID of callinstruction
              MDNode* md = bi->getMetadata("dp.md.instr.id");
              if (md) {
                // Metadata exists
                std::string call_instruction_id_str = cast<MDString>(md->getOperand(0))->getString().str();
                call_instruction_id_str.erase(0, 15);
                std::int32_t call_instruction_id = std::stoi(call_instruction_id_str);
                loop_increment_instruction_ids[loop_id] = call_instruction_id;
              }
            } else {
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
  LoopId loop_id;
  std::vector<LoopTreeNode*> children;
};

// Reconstructs the loop nesting forest of the instrumented loops of F from LoopInfo. The loops
// are identified by their __dp_loop_entry calls (in the loop headers, see CFA), and the parent of
// a loop is its closest enclosing instrumented loop. Siblings keep the order of their entry calls
// in the basic block layout. The exit calls are not used: an exit block may be laid out anywhere
// (e.g. in the middle of the body of an enclosing loop), so the order of the entry and exit calls
// does not describe the nesting. Returns one LoopTreeNode* per top-level loop; loop_ids receives
// the id of every instrumented loop.
std::vector<LoopTreeNode*> BuildLoopForest(Function& f, LoopInfo& li,
                                           std::unordered_map<const Loop*, LoopId>& loop_ids) {
  std::vector<LoopTreeNode*> roots;
  std::vector<std::pair<const Loop*, LoopTreeNode*>> nodes_in_layout_order;
  std::unordered_map<const Loop*, LoopTreeNode*> node_of_loop;

  for (BasicBlock& bb : f) {
    for (Instruction& i : bb) {
      auto ci = dyn_cast<CallInst>(&i);
      if (!ci || !ci->getCalledFunction() || ci->getCalledFunction()->getName() != "__dp_loop_entry") {
        continue;
      }
      auto const_int = dyn_cast<llvm::ConstantInt>(ci->getArgOperand(1));
      const Loop* l = li.getLoopFor(&bb);
      if (!const_int || const_int->getBitWidth() > 32 || !l || node_of_loop.count(l) > 0) {
        continue;
      }
      LoopTreeNode* node = new LoopTreeNode();
      node->loop_id = static_cast<LoopId>(const_int->getSExtValue());
      loop_ids[l] = node->loop_id;
      node_of_loop[l] = node;
      nodes_in_layout_order.push_back({l, node});
    }
  }

  for (auto& pair : nodes_in_layout_order) {
    const Loop* parent = pair.first->getParentLoop();
    while (parent && node_of_loop.count(parent) == 0) {
      parent = parent->getParentLoop();
    }
    if (parent) {
      node_of_loop[parent]->children.push_back(pair.second);
    } else {
      roots.push_back(pair.second);
    }
  }
  return roots;
}

// Frees the nodes allocated by build_loop_forest for a single tree.
void DeleteLoopTree(LoopTreeNode* node) {
  for (auto child : node->children) {
    DeleteLoopTree(child);
  }
  delete node;
}

// Assigns each loop tree node a stable position (offset) within the flat ITERATION_INSTANCE
// vector via pre-order traversal, and records the resulting loop_id sequence (used to map
// an offset back to its loop_id, e.g. for debug output and in buildStaticCalltree).
void FlattenLoopForest(LoopTreeNode* node, std::vector<LoopId>& out_sequence,
                       std::unordered_map<LoopTreeNode*, std::int32_t>& node_to_offset) {
  node_to_offset[node] = static_cast<std::int32_t>(out_sequence.size());
  out_sequence.push_back(node->loop_id);
  for (auto child : node->children) {
    FlattenLoopForest(child, out_sequence, node_to_offset);
  }
}

// converts an iteration instance to its string representation (one digit per loop position)
std::string IterationInstanceToString(const IterationInstance& instance) {
  std::string result;
  result.reserve(instance.size());
  for (auto v : instance) {
    result += std::to_string(v);
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
void GenerateStatesForNode(
    LoopTreeNode* node, const std::vector<IterationInstance>& incoming_instances,
    std::unordered_map<LoopTreeNode*, std::int32_t>& node_to_offset,
    std::unordered_map<std::string, std::unordered_map<TransitionType, std::unordered_map<LoopId, std::string>>>&
        transitions,
    bool is_top_level) {
  std::int32_t offset = node_to_offset[node];
  const LoopId loop_id = node->loop_id;

  std::vector<IterationInstance> own_instances;
  own_instances.reserve(incoming_instances.size() * 3);

  for (const auto& parent_instance : incoming_instances) {
    const std::string parent_instance_str = IterationInstanceToString(parent_instance);

    IterationInstance variants[3];
    std::string variant_strs[3];
    for (int v = 0; v < 3; ++v) {
      variants[v] = parent_instance;
      variants[v][offset] = v;
      variant_strs[v] = IterationInstanceToString(variants[v]);
      own_instances.push_back(variants[v]);
    }

    // ENTER: parent -> variant[0] (entering always starts at iteration bucket 0)
    if (is_top_level) {
      transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP][loop_id] = variant_strs[0];
    } else {
      transitions[parent_instance_str][TRANSITION_TYPE_ENTERLOOP][loop_id] = variant_strs[0];
    }

    // EXIT: any iteration bucket can be exited, always returning to the (unchanged) parent state
    const std::string exit_target = is_top_level ? "exit_points" : parent_instance_str;
    for (int v = 0; v < 3; ++v) {
      transitions[variant_strs[v]][TRANSITION_TYPE_EXITLOOP][loop_id] = exit_target;
    }

    // INCREMENT: cycle 0 -> 1 -> 2 -> 0
    transitions[variant_strs[0]][TRANSITION_TYPE_INCREMENTLOOP][loop_id] = variant_strs[1];
    transitions[variant_strs[1]][TRANSITION_TYPE_INCREMENTLOOP][loop_id] = variant_strs[2];
    transitions[variant_strs[2]][TRANSITION_TYPE_INCREMENTLOOP][loop_id] = variant_strs[0];
  }

  for (auto child : node->children) {
    GenerateStatesForNode(child, own_instances, node_to_offset, transitions, false);
  }
}

// returns all combinations of allowed loop iteration counters for the given loop nesting
// forest. Unlike a flat/chain-based enumeration (which would generate 3^N states for N loops
// total, including states that are impossible at runtime), this walks the real loop nesting
// tree and only ever branches within a single node's own subtree at a time. As a result, a
// node at depth d contributes 3^d states instead of 3^N, since its siblings (and everything
// nested inside them) are guaranteed to stay "dont care".
std::unordered_map<std::string, std::unordered_map<TransitionType, std::unordered_map<LoopId, std::string>>>
GetLoopIterationInstancesAndTransitions(std::vector<LoopTreeNode*>& forest, std::int32_t loop_count,
                                        std::unordered_map<LoopTreeNode*, std::int32_t>& node_to_offset) {
  std::unordered_map<std::string, std::unordered_map<TransitionType, std::unordered_map<LoopId, std::string>>>
      loop_iteration_instance_transitions;

  const IterationInstance root_instance(loop_count, 3);
  const std::vector<IterationInstance> root_instances{root_instance};

  for (auto root : forest) {
    GenerateStatesForNode(root, root_instances, node_to_offset, loop_iteration_instance_transitions, true);
  }

  return loop_iteration_instance_transitions;
}

// returns true if the call or invoke I is a real call, i.e. not a call of an instrumentation
// function, a clang helper or an LLVM intrinsic
static bool IsRelevantCall(Instruction* /*I*/, Function* callee) {
  if (!callee) {
    return false;
  }
  auto fn = callee->getName();
  if (fn.find("__dp_") != std::string::npos || fn.find("__clang_") != std::string::npos) {
    return false;
  }
  // LLVM intrinsics (e.g. llvm.fmuladd.*, llvm.dbg.*, llvm.memcpy.*) are lowered arithmetic or
  // metadata operations, not real calls, and have no call-graph meaning.
  if (callee->isIntrinsic()) {
    return false;
  }
  return true;
}

// returns a map from loopID to a vector of callInstructionIDs contained in the loop, i.e. in a
// basic block of the loop according to LoopInfo
std::unordered_map<std::int32_t, std::vector<std::int32_t>> GetLoopCallInstructionAffectance(
    Function& f, LoopInfo& li, std::unordered_map<const Loop*, LoopId>& loop_ids) {
  std::unordered_map<std::int32_t, std::vector<std::int32_t>> result_map;
  for (BasicBlock& bb : f) {
    const Loop* innermost = li.getLoopFor(&bb);
    if (!innermost) {
      continue;
    }
    for (Instruction& i : bb) {
      if (!isa<CallInst>(&i) && !isa<InvokeInst>(&i)) {
        continue;
      }
      if (!IsRelevantCall(&i, GetCalledFunctionThroughAliases(&i))) {
        continue;
      }
      std::int32_t call_instruction_id = GetDpInstructionId(&i);
      if (call_instruction_id == 0) {
        continue;
      }
      for (const Loop* l = innermost; l != nullptr; l = l->getParentLoop()) {
        auto pos = loop_ids.find(l);
        if (pos != loop_ids.end()) {
          result_map[pos->second].push_back(call_instruction_id);
        }
      }
    }
  }
  return result_map;
}

// inverts the given map. Returns a map from CallInstructionID to LoopIDs which affect it.
std::unordered_map<std::int32_t, std::vector<std::int32_t>> GetInvertedLoopCallInstructionAffectance(
    const std::unordered_map<std::int32_t, std::vector<std::int32_t>>& loop_call_affectance) {
  std::unordered_map<std::int32_t, std::vector<std::int32_t>> result_map;
  for (const auto& pair : loop_call_affectance) {
    auto loop_id = pair.first;
    for (auto call_inst_id : pair.second) {
      if (result_map.count(call_inst_id) == 0) {
        const std::vector<std::int32_t> tmp;
        result_map[call_inst_id] = tmp;
      }
      result_map[call_inst_id].push_back(loop_id);
    }
  }

  return result_map;
}

namespace static_callpaths {

// builds a call tree for the given Module on the basis of the statically available information
StaticCalltree BuildStaticCalltree(Module& m, const std::map<std::int32_t, LoopIdentity>& loop_id_to_identity) {
  StaticCalltree calltree;
  // explicit mapping from the digit positions of the "<function>_loopstate<digits>" labels
  // (see StaticCalltree.cpp) to the loops they describe, read by the explorer
  std::ofstream loopstate_positions_file;
  std::string loopstate_positions_path(dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler"));
  loopstate_positions_path += "/loopstate_positions.txt";
  loopstate_positions_file.open(loopstate_positions_path.data(), std::ios_base::app);
  for (Function& f : m) {
    std::cout << "BUILDING FUNCTION: " << f.getName().str() << "\n";
    // reconstruct the real loop nesting tree (preserves parent/child relationships, which is
    // required to tell true ancestors apart from mutually-exclusive sibling loops)
    std::unordered_map<const Loop*, LoopId> loop_ids;
    std::vector<LoopTreeNode*> loop_forest;
    // LoopInfo of the instrumented function (instrumentation only inserts calls, the CFG is unchanged)
    std::unique_ptr<DominatorTree> dt;
    std::unique_ptr<LoopInfo> li;
    if (!f.isDeclaration()) {
      dt = std::make_unique<DominatorTree>(f);
      li = std::make_unique<LoopInfo>(*dt);
      loop_forest = BuildLoopForest(f, *li, loop_ids);
    }
    std::vector<LoopId> sequentialized_contained_loops;
    std::unordered_map<LoopTreeNode*, std::int32_t> node_to_offset;
    for (auto root : loop_forest) {
      FlattenLoopForest(root, sequentialized_contained_loops, node_to_offset);
    }
    // <function> <position> <loop_id> <Data.xml loop node id> <file_id>:<start_line>
    for (std::size_t position = 0; position < sequentialized_contained_loops.size(); ++position) {
      auto loop_id = sequentialized_contained_loops[position];
      std::string pet_node_id = "-";
      std::string start_location = "-";
      auto identity = loop_id_to_identity.find(loop_id);
      if (identity != loop_id_to_identity.end()) {
        pet_node_id = identity->second.pet_node_id;
        start_location = identity->second.start_location;
      }
      loopstate_positions_file << f.getName().str() << " " << position << " " << loop_id << " " << pet_node_id << " "
                               << start_location << "\n";
    }
    // cerr << "seq_contained_loops: " << std::endl;
    // for (auto s : sequentialized_contained_loops){
    //   cerr << " --> " << s << std::endl;
    // }
    auto loop_entry_instruction_ids = GetLoopEntryInstructionIds(f);
    auto loop_exit_instruction_ids = GetLoopExitInstructionIds(f);
    auto loop_increment_instruction_ids = GetLoopIncrementInstructionIds(f);

    // for each loop, allow 3 values to represent the currently executed iteration
    // create one instance of the function_node in the calltree per combination of iterations.
    // The value 3 is chosen to keep the amount of total states somewhat concise, while still allowing to distinguish
    // between intra- and inter-iteration dependencies with a comparatively high probability. Valid Iteration counters
    // are 0, 1, and 2. A value of 3 acts as a "dont care" symbol. Only states that respect the real loop nesting tree
    // are generated: a loop's ancestors must be active for it to be entered, and its siblings (and everything nested
    // inside them) always remain "dont care", since they cannot be active at the same time. This bounds the number of
    // states for a given loop by 3^depth instead of 3^(total loop count).
    auto iteration_instances_and_transitions = GetLoopIterationInstancesAndTransitions(
        loop_forest, static_cast<std::int32_t>(sequentialized_contained_loops.size()), node_to_offset);

    for (auto root : loop_forest) {
      DeleteLoopTree(root);
    }

    // create StaticCalltreeNode instances for function F
    std::vector<StaticCalltreeNode*> function_node_instances;

    StaticCalltreeNode* original_function_node_ptr = calltree.GetOrInsertFunctionNode(f.getName().str());
    // the function's __dp_func_entry call identifies the function at runtime
    if (!f.isDeclaration()) {
      for (Instruction& i : f.getEntryBlock()) {
        auto ci = dyn_cast<CallInst>(&i);
        if (ci && ci->getCalledFunction() && ci->getCalledFunction()->getName() == "__dp_func_entry") {
          original_function_node_ptr->function_entry_instruction_id = GetDpInstructionId(&i);
          break;
        }
      }
    }

    std::unordered_map<std::int32_t, std::vector<StaticCalltreeNode*>> loop_activity_map;
    std::unordered_map<std::int32_t, std::vector<StaticCalltreeNode*>> loop_entry_nodes_map;
    std::unordered_map<std::string, StaticCalltreeNode*> instance_to_node_map;
    for (const auto& pair : iteration_instances_and_transitions) {
      auto instance = pair.first;

      // skip instance "entry_points"
      if (instance.find("entry_points") != std::string::npos) {
        continue;
      }

      StaticCalltreeNode* function_node_ptr = calltree.GetOrInsertFunctionNode(f.getName().str(), instance);
      function_node_instances.push_back(function_node_ptr);
      instance_to_node_map[instance] = function_node_ptr;

      // register loop activity for later use (loop active, if iteration count != 3 (i.e. don't care))
      for (std::size_t idx = 0; idx < instance.size(); ++idx) {
        const int iteration_counter = instance[idx] - '0';
        if (iteration_counter != 3) {
          // get loop id from position via lookup in sequentialized_contained_loops
          auto active_loop_id = sequentialized_contained_loops[idx];
          if (loop_activity_map.count(active_loop_id) == 0) {
            const std::vector<StaticCalltreeNode*> tmp;
            loop_activity_map[active_loop_id] = tmp;
          }
          loop_activity_map[active_loop_id].push_back(function_node_ptr);

          // check if the current instance is an entry node to the loop.
          // save for later use if so.
          if (iteration_instances_and_transitions.find("entry_points") != iteration_instances_and_transitions.end()) {
            // "entry_points" is a key
            if (iteration_instances_and_transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP].find(active_loop_id) !=
                iteration_instances_and_transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP].end()) {
              // entry point for loop is registered
              if (iteration_instances_and_transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP][active_loop_id] ==
                  instance) {
                // instance is an entry point to the loop
                if (loop_entry_nodes_map.find(active_loop_id) == loop_entry_nodes_map.end()) {
                  const std::vector<StaticCalltreeNode*> tmp;
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
    if (iteration_instances_and_transitions.find("entry_points") != iteration_instances_and_transitions.end()) {
      for (const auto& pair : iteration_instances_and_transitions["entry_points"][TRANSITION_TYPE_ENTERLOOP]) {
        auto loop_id = pair.first;
        auto loop_entry_instance = pair.second;
        calltree.AddEdge(original_function_node_ptr, instance_to_node_map[loop_entry_instance],
                         loop_entry_instruction_ids[loop_id]);
      }
    }

    // add transition edges between loop iteration nodes
    for (const auto& pair_0 : iteration_instances_and_transitions) {
      auto source_instance = pair_0.first;
      if (source_instance.find("entry_points") != std::string::npos) {
        // ignore the "entry_points" key in the transition map
        continue;
      }
      for (const auto& pair_1 : pair_0.second) {
        auto transition_type = pair_1.first;
        for (const auto& pair_2 : pair_1.second) {
          auto loop_id = pair_2.first;
          auto target_instance = pair_2.second;
          // determine nodes
          auto source_node = instance_to_node_map[source_instance];
          StaticCalltreeNode* target_node = nullptr;
          if (target_instance.find("exit_points") != std::string::npos) {
            // target is leaving a function scope, i.e. goes back to the function node
            target_node = original_function_node_ptr;
          } else {
            target_node = instance_to_node_map[target_instance];
          }

          // determine the trigger instructions. Instruction id 0 is reserved for fall-through
          // transitions (followed right after any transition into the source state), so a
          // transition without a trigger instruction must not be created.
          std::vector<std::int32_t> trigger_instructions;
          if (transition_type == TRANSITION_TYPE_ENTERLOOP) {
            trigger_instructions.push_back(loop_entry_instruction_ids[loop_id]);
          } else if (transition_type == TRANSITION_TYPE_EXITLOOP) {
            // a loop with several exit blocks is left through any of their exit calls
            trigger_instructions = loop_exit_instruction_ids[loop_id];
          } else if (transition_type == TRANSITION_TYPE_INCREMENTLOOP) {
            auto increment = loop_increment_instruction_ids.find(loop_id);
            if (increment != loop_increment_instruction_ids.end()) {
              trigger_instructions.push_back(increment->second);
            } else {
              // loops without __dp_loop_incr (instrument_loop skips loops without a source location
              // and loops of a single basic block) start a new iteration whenever their header, and
              // thus the loop entry call, is executed again
              trigger_instructions.push_back(loop_entry_instruction_ids[loop_id]);
            }
          }
          // create edges
          for (auto trigger_instruction : trigger_instructions) {
            if (trigger_instruction != 0) {
              calltree.AddEdge(source_node, target_node, trigger_instruction);
            }
          }
        }
      }
    }

    // get connection between loops and called functions inside the loops
    std::unordered_map<std::int32_t, std::vector<std::int32_t>> loop_call_affectance;
    if (li) {
      loop_call_affectance = GetLoopCallInstructionAffectance(f, *li, loop_ids);
    }
    auto inverted_loop_call_affectance = GetInvertedLoopCallInstructionAffectance(loop_call_affectance);

    for (BasicBlock& bb : f) {
      for (Instruction& i : bb) {
        if (!isa<CallInst>(&i) && !isa<InvokeInst>(&i)) {
          continue;
        }
        // resolves aliases, e.g. calls of constructors (see getCalledFunctionThroughAliases)
        Function* callee = GetCalledFunctionThroughAliases(&i);
        if (!IsRelevantCall(&i, callee)) {
          continue;
        }
        // register CallInstruction Node in StaticCalltree
        std::int32_t call_instruction_id = GetDpInstructionId(&i);
        if (call_instruction_id == 0) {
          continue;
        }
        StaticCalltreeNode* call_instruction_node_ptr = calltree.GetOrInsertInstructionNode(call_instruction_id);
        calltree.AddEdge(original_function_node_ptr, call_instruction_node_ptr, call_instruction_id);
        // connect to nodes if the loop contains the call and the loop is "active" and node is an entry node to the
        // loop, i.e. iteration count is 0
        auto parent_loops = inverted_loop_call_affectance[call_instruction_id];
        for (auto parent_loop_id : parent_loops) {
          for (auto node_ptr : loop_activity_map[parent_loop_id]) {
            calltree.AddEdge(node_ptr, call_instruction_node_ptr, call_instruction_id);
          }
        }
        StaticCalltreeNode* callee_node_ptr = calltree.GetOrInsertFunctionNode(callee->getName().str());
        calltree.AddEdge(call_instruction_node_ptr, callee_node_ptr, 0);
      }
    }
  }
  loopstate_positions_file.close();
  return calltree;
}

}  // namespace static_callpaths
