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

// #define DEBUG_GRAPH_HPP

// STL IMPORTS
#include <algorithm>
#include <fstream>
#include <iostream>
#include <iterator>
#include <list>
#include <map>
#include <set>
#include <stack>
#include <utility>
#include <vector>

template <typename InstructionNodeT>
class InstructionNode {
 private:
  InstructionNodeT item_;

 public:
  explicit InstructionNode(InstructionNodeT item) : item_(item) {}

  ~InstructionNode() {}

  InstructionNodeT GetItem() const { return item_; }
};

template <typename InstructionNodeT>
class Edge {
 private:
  InstructionNode<InstructionNodeT>* src_;
  InstructionNode<InstructionNodeT>* dst_;

 public:
  Edge(InstructionNode<InstructionNodeT>* src, InstructionNode<InstructionNodeT>* dst) : src_(src), dst_(dst) {}

  ~Edge() {}

  InstructionNode<InstructionNodeT>* GetSrc() const { return src_; }

  InstructionNode<InstructionNodeT>* GetDst() const { return dst_; }
};

template <typename InstructionNodeT>
class Graph {
 private:
  std::list<InstructionNode<InstructionNodeT>*> instruction_nodes_list_;
  unsigned next_int_key_ = 0;
  // This stores a map from object of type T to it's respective pair (Key,
  // InstructionNode)
  std::map<InstructionNodeT, std::pair<int, InstructionNode<InstructionNodeT>*>> instruction_nodes_;
  std::list<Edge<InstructionNodeT>*> edges_list_;
  // This map stores all the outcoming edges from node of type T
  std::map<InstructionNode<InstructionNodeT>*, std::set<Edge<InstructionNodeT>*>> out_edges_;
  // This map stores all the incoming edges to node of type T
  std::map<InstructionNode<InstructionNodeT>*, std::set<Edge<InstructionNodeT>*>> in_edges_;

 public:
  Graph() {}

  ~Graph() {
    for (auto& n : instruction_nodes_list_) {
      delete n;
    }
    for (auto& e : edges_list_) {
      delete e;
    }
  }

  InstructionNode<InstructionNodeT>* operator[](InstructionNodeT item) const { return GetInstructionNode(item); }

  InstructionNode<InstructionNodeT>* AddInstructionNode(InstructionNodeT item) {
    if (instruction_nodes_.count(item) == 0) {
      InstructionNode<InstructionNodeT>* instruction_node = new InstructionNode<InstructionNodeT>(item);
      instruction_nodes_[item] = std::pair<int, InstructionNode<InstructionNodeT>*>(next_int_key_, instruction_node);
      instruction_nodes_list_.push_back(instruction_node);
      next_int_key_++;
      return instruction_node;
    }
#ifdef DEBUG_GRAPH_HPP
    std::cout << "\nTrying to add an already added item.\n";
#endif
    return instruction_nodes_.find(item)->second.second;
  }

  InstructionNode<InstructionNodeT>* GetInstructionNode(InstructionNodeT item) {
    if (instruction_nodes_.count(item) == 0) {
      return nullptr;
    }
    return instruction_nodes_.find(item)->second.second;
  }

  InstructionNode<InstructionNodeT>* GetInstructionNodeByIndex(const int index) const {
    for (const auto& pair : instruction_nodes_) {
      if (pair.second.first == index) {
        return pair.second.second;
      }
    }
    return nullptr;
  }

  int GetInstructionNodeIndex(InstructionNodeT item) const {
    if (instruction_nodes_.count(item) == 0) {
      return -1;
    }
    return instruction_nodes_.find(item)->second.first;
  }

  int GetInstructionNodeIndex(InstructionNode<InstructionNodeT>* instruction_node) const {
    return GetInstructionNodeIndex(instruction_node->GetItem());
  }

  std::list<InstructionNode<InstructionNodeT>*> GetInstructionNodes() const { return instruction_nodes_list_; }

  Edge<InstructionNodeT>* AddEdge(InstructionNode<InstructionNodeT>* src, InstructionNode<InstructionNodeT>* dst) {
    for (const Edge<InstructionNodeT>* ed : out_edges_[src]) {
      if (ed->GetDst() == dst) {
        return nullptr;
      }
    }

    Edge<InstructionNodeT>* edge = new Edge<InstructionNodeT>(src, dst);
    out_edges_[src].insert(edge);
    in_edges_[dst].insert(edge);
    edges_list_.push_back(edge);
    return edge;
  }

  Edge<InstructionNodeT>* AddEdge(InstructionNodeT src, InstructionNodeT dst) {
    InstructionNode<InstructionNodeT>* src_node = GetInstructionNode(src);
    InstructionNode<InstructionNodeT>* dst_node = GetInstructionNode(dst);

    if (src_node == nullptr) {
      src_node = AddInstructionNode(src);
    }
    if (dst_node == nullptr) {
      dst_node = AddInstructionNode(dst);
    }

    return AddEdge(src_node, dst_node);
  }

  std::set<Edge<InstructionNodeT>*> GetInEdges(InstructionNode<InstructionNodeT>* instruction_node) {
    std::set<Edge<InstructionNodeT>*> in_edges;
    if (in_edges_.find(instruction_node) != in_edges_.end()) {
      in_edges = in_edges_[instruction_node];
    }

    return in_edges;
  }

  std::set<Edge<InstructionNodeT>*> GetInEdges(InstructionNodeT item) {
    InstructionNode<InstructionNodeT>* instruction_node = GetInstructionNode(item);
    return GetInEdges(instruction_node);
  }

  std::set<Edge<InstructionNodeT>*> GetOutEdges(InstructionNode<InstructionNodeT>* instruction_node) {
    std::set<Edge<InstructionNodeT>*> out_edges;
    if (out_edges_.count(instruction_node) != 0) {
      return out_edges_[instruction_node];
    }
    return out_edges;
  }

  std::set<Edge<InstructionNodeT>*> GetOutEdges(InstructionNodeT item) { return GetOutEdges(GetInstructionNode(item)); }

  void RemoveEdge(Edge<InstructionNodeT>* e) {
    auto out = e->GetSrc();
    auto in = e->GetDst();
    edges_list_.remove(e);
    out_edges_[out].erase(e);
    in_edges_[in].erase(e);
  }

  std::list<Edge<InstructionNodeT>*> GetEdges() const { return edges_list_; }

  int size() const { return next_int_key_; }
};
