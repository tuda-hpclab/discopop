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
#include <atomic>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "StaticCalltree.hpp"

class StaticCallPathTree;  // forward declaration

class StaticCallPathTreeNode {
 public:
  StaticCalltreeNode* base_node;
  const std::uint32_t path_id;
  std::mutex mtx;
  std::unordered_map<int32_t, std::uint32_t> state_transitions;

  std::vector<StaticCallPathTreeNode*>
      successors;  // use vectors due to the assumption, that a single path generally has only a small number of
                   // successors. Save time and space for creating and managing a hashset or similar.
  StaticCallPathTreeNode* prefix;

  StaticCallPathTreeNode(std::uint32_t path_id, StaticCalltreeNode* base_node)
      : base_node(base_node), path_id(path_id), prefix(nullptr) {}

  StaticCallPathTreeNode(std::uint32_t path_id, StaticCalltreeNode* base_node, StaticCallPathTreeNode* prefix)
      : base_node(base_node), path_id(path_id), prefix(prefix) {}

  ~StaticCallPathTreeNode();

  StaticCallPathTreeNode* GetOrRegisterSuccessor(StaticCallPathTree* tree, StaticCalltreeNode* successor_node);

  void RegisterTransition(int32_t trigger_instruction_id, std::uint32_t target_path_id);

  [[nodiscard]] std::string ToDotString();
  [[nodiscard]] std::string GetPathString() const;
};

class StaticCallPathTree {
 private:
  std::atomic<std::uint32_t> next_free_path_id_{0};
  // std::mutex next_free_path_id_mtx;

 public:
  StaticCallPathTreeNode* root = nullptr;
  std::vector<StaticCallPathTreeNode*> all_nodes;
  std::mutex all_nodes_mtx;

  StaticCallPathTree();
  explicit StaticCallPathTree(std::uint32_t start_path_id);  // so that ids don't overlap between modules
  ~StaticCallPathTree();
  std::string ToDotString() const;

  [[nodiscard]] std::uint32_t GetNextFreePathId();
  std::uint32_t GetCurrentFreePathId() const;  // returns next free path id
  void RegisterNodeInAllNodes(StaticCallPathTreeNode* node_ptr);
};
