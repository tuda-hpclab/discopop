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

using namespace std;

template <typename InstructionNodeT> class InstructionNode {
private:
  InstructionNodeT item;

public:
  InstructionNode(InstructionNodeT _item) : item(_item) {}

  ~InstructionNode(){};

  InstructionNodeT getItem() const { return item; }
};

template <typename InstructionNodeT> class Edge {
private:
  InstructionNode<InstructionNodeT> *src;
  InstructionNode<InstructionNodeT> *dst;

public:
  Edge(InstructionNode<InstructionNodeT> *_src, InstructionNode<InstructionNodeT> *_dst) : src(_src), dst(_dst){};

  ~Edge(){};

  InstructionNode<InstructionNodeT> *getSrc() const { return src; }

  InstructionNode<InstructionNodeT> *getDst() const { return dst; }
};

template <typename InstructionNodeT> class Graph {
private:
  std::list<InstructionNode<InstructionNodeT> *> instructionNodesList;
  unsigned nextIntKey = 0;
  // This stores a map from object of type T to it's respective pair (Key,
  // InstructionNode)
  std::map<InstructionNodeT, std::pair<int, InstructionNode<InstructionNodeT> *>> instructionNodes;
  std::list<Edge<InstructionNodeT> *> edgesList;
  // This map stores all the outcoming edges from node of type T
  std::map<InstructionNode<InstructionNodeT> *, std::set<Edge<InstructionNodeT> *>> outEdges;
  // This map stores all the incoming edges to node of type T
  std::map<InstructionNode<InstructionNodeT> *, std::set<Edge<InstructionNodeT> *>> inEdges;

public:
  Graph(){};

  ~Graph() {
    for (auto &n : instructionNodesList)
      delete n;
    for (auto &e : edgesList)
      delete e;
  }

  InstructionNode<InstructionNodeT> *operator[](InstructionNodeT item) const { return getInstructionNode(item); }

  InstructionNode<InstructionNodeT> *addInstructionNode(InstructionNodeT item) {
    if (instructionNodes.count(item) == 0) {
      InstructionNode<InstructionNodeT> *instructionNode = new InstructionNode<InstructionNodeT>(item);
      instructionNodes[item] =
          std::make_pair<int, InstructionNode<InstructionNodeT> *>(nextIntKey, std::move(instructionNode));
      instructionNodesList.push_back(instructionNode);
      nextIntKey++;
      return instructionNode;
    } else {
#ifdef DEBUG_GRAPH_HPP
      std::cout << "\nTrying to add an already added item.\n";
#endif
      return instructionNodes.find(item)->second.second;
    }
  }

  InstructionNode<InstructionNodeT> *getInstructionNode(InstructionNodeT item) {
    if (instructionNodes.count(item) == 0)
      return nullptr;
    return instructionNodes.find(item)->second.second;
  }

  InstructionNode<InstructionNodeT> *getInstructionNodeByIndex(const int index) const {
    for (const auto &pair_ : instructionNodes) {
      if (pair_.second.first == index) {
        return pair_.second.second;
      }
    }
    return nullptr;
  }

  int getInstructionNodeIndex(InstructionNodeT item) const {
    if (instructionNodes.count(item) == 0)
      return -1;
    return instructionNodes.find(item)->second.first;
  }

  int getInstructionNodeIndex(InstructionNode<InstructionNodeT> *instructionNode) const {
    return getInstructionNodeIndex(instructionNode->getItem());
  }

  std::list<InstructionNode<InstructionNodeT> *> getInstructionNodes() const { return instructionNodesList; }

  Edge<InstructionNodeT> *addEdge(InstructionNode<InstructionNodeT> *src, InstructionNode<InstructionNodeT> *dst) {
    for (Edge<InstructionNodeT> *ed : outEdges[src]) {
      if (ed->getDst() == dst) {
        return nullptr;
      }
    }

    Edge<InstructionNodeT> *edge = new Edge<InstructionNodeT>(src, dst);
    outEdges[src].insert(edge);
    inEdges[dst].insert(edge);
    edgesList.push_back(edge);
    return edge;
  }

  Edge<InstructionNodeT> *addEdge(InstructionNodeT src, InstructionNodeT dst) {
    InstructionNode<InstructionNodeT> *src_ = getInstructionNode(src);
    InstructionNode<InstructionNodeT> *dst_ = getInstructionNode(dst);

    if (src_ == nullptr)
      src_ = addInstructionNode(src);
    if (dst_ == nullptr)
      dst_ = addInstructionNode(dst);

    return addEdge(src_, dst_);
  }

  std::set<Edge<InstructionNodeT> *> getInEdges(InstructionNode<InstructionNodeT> *instructionNode) {
    std::set<Edge<InstructionNodeT> *> inEdges_;
    if (inEdges.find(instructionNode) != inEdges.end())
      inEdges_ = inEdges[instructionNode];

    return inEdges_;
  }

  std::set<Edge<InstructionNodeT> *> getInEdges(InstructionNodeT item) {
    InstructionNode<InstructionNodeT> *instructionNode = getInstructionNode(item);
    return getInEdges(instructionNode);
  }

  std::set<Edge<InstructionNodeT> *> getOutEdges(InstructionNode<InstructionNodeT> *instructionNode) {
    std::set<Edge<InstructionNodeT> *> outEdges_;
    if (outEdges.count(instructionNode) != 0)
      return outEdges[instructionNode];
    return outEdges_;
  }

  std::set<Edge<InstructionNodeT> *> getOutEdges(InstructionNodeT item) {
    return getOutEdges(getInstructionNode(item));
  }

  void removeEdge(Edge<InstructionNodeT> *e) {
    auto out = e->getSrc();
    auto in = e->getDst();
    edgesList.remove(e);
    outEdges[out].erase(e);
    inEdges[in].erase(e);
  }

  std::list<Edge<InstructionNodeT> *> getEdges() const { return edgesList; }

  int size() const { return nextIntKey; }
};
